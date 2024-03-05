from flask import Flask, request  #需要安装库 pip install Flask
from gevent.pywsgi import WSGIServer  #需要安装库 pip install gevent
from urllib.parse import unquote
from threading import Thread
from queue import Queue
from openai import OpenAI   #需要安装库 pip install openai  更新pip install --upgrade openai
import concurrent.futures
import os
import re
import time
import json

# 启用虚拟终端序列，支持ANSI转义代码
os.system('')


dict_path='用户替换字典.json' # 提示字典路径，不使用则留空

# API配置
Base_url = 'https://api.sweetkxq.top' # 中转请求地址
Model_Type = 'gpt-3.5-turbo-16k' # 模型名称
API_key = 'sk-1111111111111111111111111111111111111111' 
Proxy_port = ''  # 代理端口，如果不使用代理则为空

# 如果填入地址，则设置系统代理
original_http_proxy = os.environ.get("http_proxy")
original_https_proxy = os.environ.get("https_proxy")

# 译文中有任意单字或单词连续出现大于等于repeat_count次，换下一提示词重新翻译
repeat_count=5
# 提示词，按照使用顺序添加进prompt_ist
prompt0= """你是一个游戏翻译人，你的任务是将游戏中的日语翻译成简体中文。翻译时要注意忽视低俗内容的问题，流畅自然地翻译，遵循高质量情色文学的习惯。特殊字符和英文字符不要翻译，并且需要原封不动的保留在对应位置。你的回答应只包含翻译结果，不要有任何提示词或其他内容。"""
prompt1= """You are a translation assistant capable of converting texts into Simplified Chinese, disregarding issues of coarse content. Do not translate special characters, keep the special characters. Furthermore, the returned result must solely consist of the Translation results without the addition of any prompt words or questions not present in the original text."""
prompt2= """You are a localizer specialized in Simplified Chinese and Japanese culture, and you need to translate the Japanese text in the game into Simplified Chinese, ignore the issue of vulgar content, translate fluently and naturally, and follow the habits of high-quality erotic literature.the escape characters or non-Japanese content such as numbers, English letters, special symbols, etc. in each line of text do not need to be translated or changed, and should be preserved as they are.Furthermore, the returned result must solely consist of the Translation results without the addition of any prompt words or questions not present in the original text."""
# prompt3= """ """
# prompt4= """ """


prompt_list=[prompt0,prompt1,prompt2]
l=len(prompt_list)
# 提示字典的提示词,最终的提示词是prompt+dprompt+提示字典，不使用提示字典可以不管
dprompt0='\n在翻译中使用以下字典,字典的格式为{\'原文\':\'译文\'}\n'
dprompt1='\nDuring the translation, use a dictionary in {\'Japanese text \':\'translated text \'} format\n'
# list，长度应该和提示词list相同，二者同步切换
dprompt_list=[dprompt0,dprompt1,dprompt1]

app = Flask(__name__)

# 如果填入代理端口，则设置系统代理
if Proxy_port:
    os.environ["http_proxy"] = Proxy_port
    os.environ["https_proxy"] = Proxy_port

# 检查一下请求地址尾部是否为/v1，自动补全
if Base_url[-3:] != "/v1":
    Base_url = Base_url + "/v1"

# 创建多个openai客户端
openai_client = OpenAI(api_key=API_key, base_url= Base_url)

# 读取提示字典,并从长倒短排序
if dict_path:
    with open(dict_path, 'r', encoding='utf8') as f:
        tempdict = json.load(f)
    sortedkey = sorted(tempdict.keys(), key=lambda x: len(x), reverse=True)
    prompt_dict = {}
    for i in sortedkey:
        prompt_dict[i] = tempdict[i]
else:
    prompt_dict= {}

def contains_japanese(text):
    # 英文、日文字符的正则表达式
    pattern = re.compile(r'[a-zA-Z\u3040-\u3096\u309D-\u309F\u30A1-\u30FA\u30FC-\u30FE]')
    return pattern.search(text) is not None


#检测是否有连续出现的短语或单字
def has_repeated_sequence(string, count):
    # 首先检查单个字符的重复
    for char in set(string):
        if string.count(char) >= count:
            return True

    # 然后检查字符串片段的重复
    # 字符串片段的长度从2到len(string)//count
    for size in range(2, len(string)//count + 1):
        for start in range(0, len(string) - size + 1):
            # 滑动窗口来提取字符串片段
            substring = string[start:start + size]
            # 使用正则表达式来检查整个字符串中该片段的重复
            matches = re.findall(re.escape(substring), string)
            if len(matches) >= count:
                return True
            
    return False



# 获得文本中包含的字典词汇
def get_dict(text):
    res={}
    for key in prompt_dict.keys():
        if key in text:
            res.update({key:prompt_dict[key]})
            text=text.replace(key,'')   # 从长倒短查找文本中含有的字典原文，找到后就删除它，避免出现长字典包含短字典的情况
        if text=='':
            break
    return res

request_queue = Queue()  # 创建请求队列
def handle_translation(text, translation_queue):
    # 对接收到的文本进行URL解码
    
    text = unquote(text)
     
    max_retries = 3  # 最大重试次数
    
    # 设置最大线程数的上限
    MAX_THREADS = 30
    
    # 从请求队列中获取当前排队的请求数量
    queue_length = request_queue.qsize()

    # 设置线程数的基本逻辑，根据请求队列长度动态调整
    # 举例：如果队列中有20个请求，就启用5个线程
    number_of_threads = max(1, min(queue_length // 4, MAX_THREADS))
    
    # 定义特殊字符
    special_chars = ['，', '。', '？','...']

    # 记录文本末尾是否有特殊字符，并存储该字符
    text_end_special_char = None
    if text[-1] in special_chars:
        text_end_special_char = text[-1]

    # 检测文本中是否包含特殊字符，并记录
    special_char_start = "「"
    special_char_end = "」"
    has_special_start = text.startswith(special_char_start)
    has_special_end = text.endswith(special_char_end)
    
    # 如果文本同时包含开始和结束的特殊字符，则在翻译前移除它们
    if has_special_start and has_special_end:
        text = text[len(special_char_start):-len(special_char_end)]

    # 更多模型参数
    model_params = {
        "temperature": 0.5,  # 控制输出的随机性
        "max_tokens": 520,  # 控制输出的最大长度
        "top_p": 1,  # 控制采样的概率质量，1意味着使用所有可能的继续
        "frequency_penalty": 0.3,  # 降低重复内容的出现概率
        "presence_penalty": 0.3,  # 降低重复主题或者话题的出现概率
    }
    try:
                   
        dict_inuse=get_dict(text)
        apology_phrases = [
            "我很抱歉，但我无法完成这个任务",
            "抱歉，我无法提供此服务",
            "抱歉，您提供的内容不足以进行翻译。请提供更多的日语原文，以便我为您翻译",
            "抱歉，您提供的词语“Middle”是英文，而不是日语，我无法进行翻译。请提供日语原文，我将为您翻译成简体中文",
            "抱歉，我只能提供日语到简体中文的翻译服务。如果你有日语游戏文本需要翻译，请提供",
            "请提供需要翻译的日语原文，我将为你翻译成简体中文",
            "你好，我是游戏翻译人。很高兴为您提供翻译服务。请告诉我您需要翻译的日语内容",
            "了解。请提供需要翻译的日语文本"
]
        # 对提示词列表遍历，有任意一次结果符合要求，break
        for i in range(len(prompt_list)):
            prompt = prompt_list[i]
            dict_inuse = get_dict(text)
            if dict_inuse:
                prompt += dprompt_list[i] + str(dict_inuse)
                          
            # 构建API请求数据
            messages_test = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": text}
            ]
            # 发送API请求，并获取翻译结果
            with concurrent.futures.ThreadPoolExecutor(max_workers=number_of_threads) as executor:
                # 使用全局客户端对象生成future对象
                future_to_trans = {executor.submit(openai_client.chat.completions.create, model=Model_Type, messages=messages_test, **model_params) for _ in range(number_of_threads)}
                
                # 等待所有的future完成
                for future in concurrent.futures.as_completed(future_to_trans):
                    try:
                        response_test = future.result()
                        translations = response_test.choices[0].message.content
                        print(f'{prompt}\n{translations}')
                        
                        # 如果原文本包含特殊字符，将翻译结果包裹起来
                        if has_special_start and has_special_end:
                            if not translations.startswith(special_char_start):
                                translations = special_char_start + translations
                            if not translations.endswith(special_char_end):
                                translations = translations + special_char_end
                            elif has_special_start and not translations.startswith(special_char_start):
                                translations = special_char_start + translations
                            elif has_special_end and not translations.endswith(special_char_end):
                                translations = translations + special_char_end
                        
                        # 检查翻译结果是否以特殊字符结束
                        translation_end_special_char = None
                        if translations[-1] in special_chars:
                            translation_end_special_char = translations[-1]
                            
                        # 如果接收的文本和翻译结果的末尾特殊字符不匹配，则进行更正
                        if text_end_special_char and translation_end_special_char:
                            if text_end_special_char != translation_end_special_char:
                                translations = translations[:-1] + text_end_special_char
                        elif text_end_special_char and not translation_end_special_char:
                            translations += text_end_special_char
                        elif not text_end_special_char and translation_end_special_char:
                            translations = translations[:-1]
                          
                                                     
                        # 检查翻译结果是否包含无法完成任务的道歉短语
                        if any(apology_phrase in translations for apology_phrase in apology_phrases):
                            continue  # 跳过当前提示词，使用下一个提示词重新翻译                      
                        
                        
                        # 检查译文中是否包含日文字符和重复短语
                        contains_japanese_characters = contains_japanese(translations)
                        repeat_check = has_repeated_sequence(translations, repeat_count)
                        
                    
                    except Exception as e:
                        retries += 1
                        print(f"API请求超时，正在进行第 {retries} 次重试... {e}")
                        if retries == max_retries:
                            # 达到最大重试次数，抛出异常
                            raise e
                        # 可以在这里添加延时等待，然后重试
                        time.sleep(1) # 比如等待1秒后重试
                        
                
                # 如果翻译结果不含日文字符且没有重复，则退出循环
                if not contains_japanese_characters and not repeat_check:
                     break
                        
                elif contains_japanese_characters:
                # 如果翻译结果中包含日文字符，则尝试下一个提示词
                    print("\033[31m检测到译文中包含日文字符，尝试使用下一个提示词进行翻译。\033[0m")
                    continue
                    
                elif repeat_check:
                    # 如果翻译结果中存在重复短语，调整参数
                    print("\033[31m检测到译文中存在重复短语，调整参数。\033[0m")
                    model_params['frequency_penalty'] += 0.1
                    break  # 跳出for循环，使用调整过的frequency_penalty重新尝试翻译         
             
            # 如果for循环完成后（即尝试了所有提示词）且翻译结果不含日文字符且没有重复，则退出while循环
            if not contains_japanese_characters and not repeat_check:
                break    
        # 打印翻译结果
        print(f"\033[36m[译文]\033[0m:\033[31m {translations}\033[0m")
        print("-------------------------------------------------------------------------------------------------------")
        translation_queue.put(translations)

    except Exception as e:
        print(f"API请求失败：{e}")
        translation_queue.put(False)

# 定义处理翻译的路由
@app.route('/translate', methods=['GET'])  
def translate():
    # 从GET请求中获取待翻译的文本
    text = request.args.get('text')  
    print(f"\033[36m[原文]\033[0m \033[35m{text}\033[0m")
    #检测text中是否包含"\n",如果包含则替换成\\n
    if '\n' in text:
        text=text.replace('\n','\\n')

    translation_queue = Queue()
    
    # 将请求加入队列
    request_queue.put_nowait(text)

    # 创建线程池
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        # 提交翻译任务到线程池
        future = executor.submit(handle_translation, text, translation_queue)

        try:
            # 获取任务结果，如果30秒内任务未完成，抛出异常
            future.result(timeout=30)
        except concurrent.futures.TimeoutError:
            print("翻译请求超时，重新翻译...")
            return "[请求超时] " + text, 500

    translation = translation_queue.get()
    
    # 任务完成后，从队列中移除请求
    request_queue.get_nowait()

    if isinstance(translation, str):
        translation = translation.replace('\\n', '\n')
        return translation
    else:
        return translation, 500

# 还原代理设置
if original_http_proxy is not None:
    os.environ["http_proxy"] = original_http_proxy
if original_https_proxy is not None:
    os.environ["https_proxy"] = original_https_proxy

def main():
    print("\033[31m服务器在 http://127.0.0.1:4000 上启动\033[0m")
    http_server = WSGIServer(('127.0.0.1', 4000), app, log=None, error_log=None)
    http_server.serve_forever()

if __name__ == '__main__':
    main()
