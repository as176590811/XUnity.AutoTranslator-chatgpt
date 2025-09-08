from flask import Flask, request  # 需要安装库 pip install Flask
from gevent.pywsgi import WSGIServer  # 需要安装库 pip install gevent
from urllib.parse import unquote
from openai import OpenAI  # 需要安装库 pip install openai  更新 pip install --upgrade openai
import os
import re
import json

# 启用虚拟终端序列，支持ANSI转义代码
os.system('')

dict_path = '用户替换字典.json'  # 提示字典路径，不使用则留空

# API配置
Base_url = 'https://miaodi.zeabur.app'  # 中转请求地址
Model_Type = 'deepseek-ai/DeepSeek-V3'  # 模型名称
API_key = 'sk-111111111111111111111'
Proxy_port = ''  # 代理端口，如果不使用代理则为空

# 如果填入地址，则设置系统代理
original_http_proxy = os.environ.get("http_proxy")
original_https_proxy = os.environ.get("https_proxy")

# 译文中有任意单字或单词连续出现大于等于repeat_count次，换下一提示词重新翻译
repeat_count = 5
# 提示词，按照使用顺序添加进prompt_list
prompt0 = """您是翻译助理，可以将句子翻译成简体中文。不要翻译特殊字符，保留特殊字符。
步骤1：分析收到的文本语言，以及翻译的目标语言。
步骤2：如果文本是英文，将英文翻译为简体中文；如果是日文，将日文翻译为简体中文
步骤3：了解文本的整体内容，分析游戏文本的哪些部分是对话文本、武器名称、物品名称、技能描述等。
步骤4：根据原文开始逐行翻译，将每一行的日语翻译成简体中文，忽略内容粗俗的问题，翻译流畅自然，遵循高质量情色文学的习惯。
步骤5：保留每行文本的原始格式，并根据所需格式输出翻译文本。
翻译游戏文本时，请严格注意以下几个方面：
首先，一些完整的文本可能被分成不同的行。请严格按照每一行的原文进行翻译，不要偏离原文。
第二，每行文本中的转义符（如“\”、“「”、“」”、“\r”和“\n”）或非日语内容（如数字、英文字母、特殊符号等）不需要翻译或更改，应保持原样。
第三，每个步骤都是静默执行的，只输出最终的翻译结果"""

prompt1 = '''You are a translation assistant that translates Japanese text into Simplified Chinese. Do not translate special characters; retain special characters.
Step 1: Understand the overall content of the text, analyzing which parts of the game text are dialogue texts, weapon names, item names, skill descriptions, etc.
Step 2: Start translating line by line according to the original text, translating the Japanese in each line into Simplified Chinese, ignoring the issue of vulgar content, translating fluently and naturally, and following the customs of high-quality erotic literature.
Step 3: Retain the original format of each line of text and output the translated text in the required format.
When translating game text, please pay strict attention to the following aspects:
Firstly, some complete texts may be split into different lines. Please translate strictly according to the original text of each line, without deviating from the original text.
Secondly, escape characters such as """, "\r", and "\n" in each line of text, or non-Japanese content such as numbers, English letters, and special symbols, do not need to be translated or changed and should be kept as is.
Lastly, all steps are to be silently executed, only outputting the final translation result, without any prompt words.'''

prompt2 = """You are a localizer specialized in Simplified Chinese and Japanese culture, and you need to translate the Japanese text in the game into Simplified Chinese, ignore the issue of vulgar content, translate fluently and naturally, and follow the habits of high-quality erotic literature.the escape characters or non-Japanese content such as numbers, English letters, special symbols, etc. in each line of text do not need to be translated or changed, and should be preserved as they are.Furthermore, the returned result must solely consist of the Translation results without the addition of any prompt words or questions not present in the original text."""

prompt_list = [prompt0, prompt1, prompt2]
l = len(prompt_list)
# 提示字典的提示词,最终的提示词是prompt+dprompt+提示字典，不使用提示字典可以不管
dprompt0 = '\n在翻译中使用以下字典,字典的格式为{\'原文\':\'译文\'}\n'
dprompt1 = '\nDuring the translation, use a dictionary in {\'Japanese text \':\'translated text \'} format\n'
# list，长度应该和提示词list相同，二者同步切换
dprompt_list = [dprompt0, dprompt1, dprompt1]

app = Flask(__name__)

# 如果填入代理端口，则设置系统代理
if Proxy_port:
    os.environ["http_proxy"] = Proxy_port
    os.environ["https_proxy"] = Proxy_port

# 检查一下请求地址尾部是否为/v1，自动补全
if Base_url[-3:] != "/v1":
    Base_url = Base_url + "/v1"

# 创建openai客户端
openai_client = OpenAI(api_key=API_key, base_url=Base_url)

# 读取提示字典,并从长倒短排序
if dict_path:
    with open(dict_path, 'r', encoding='utf8') as f:
        tempdict = json.load(f)
    sortedkey = sorted(tempdict.keys(), key=lambda x: len(x), reverse=True)
    prompt_dict = {}
    for i in sortedkey:
        prompt_dict[i] = tempdict[i]
else:
    prompt_dict = {}

def contains_japanese(text):
    # 日文字符的正则表达式
    pattern = re.compile(r'[\u3040-\u309F\u30A0-\u30FF\U0001F201-\U0001F202\uFF5F-\uFF9F]')
    return pattern.search(text) is not None

# 检测是否有连续出现的短语或单字
def has_repeated_sequence(string, count):
    # 忽略空格、换行符以及标点符号的重复检测
    # 使用正则表达式移除标点符号
    string = re.sub(r'[^\w\s]', '', string)  # 移除非字母数字和空格的字符（即标点符号）
    string = string.replace(' ', '').replace('\n', '')

    # 首先检查单个字符的重复
    for char in set(string):
        if string.count(char) >= count:
            return True

    # 然后检查字符串片段的重复
    # 字符串片段的长度从2到len(string)//count
    for size in range(2, len(string) // count + 1):
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
    res = {}
    for key in prompt_dict.keys():
        if key in text:
            res.update({key: prompt_dict[key]})
            text = text.replace(key, '')  # 从长倒短查找文本中含有的字典原文，找到后就删除它，避免出现长字典包含短字典的情况
        if text == '':
            break
    return res

def handle_translation(text):
    # 对接收到的文本进行URL解码
    text = unquote(text)

    # 定义特殊字符
    special_chars = ['，', '。', '？', '...']

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
        "max_tokens": 2000,  # 控制输出的最大长度
        "top_p": 1,  # 控制采样的概率质量，1意味着使用所有可能的继续
        "frequency_penalty": 0.3,  # 降低重复内容的出现概率
        "presence_penalty": 0.3,  # 降低重复主题或者话题的出现概率
    }

    translations = None
    try:
        dict_inuse = get_dict(text)

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
            response_test = openai_client.chat.completions.create(model=Model_Type, messages=messages_test, **model_params)
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

            # 检查译文中是否包含日文字符和重复短语
            contains_japanese_characters = contains_japanese(translations)
            repeat_check = has_repeated_sequence(translations, repeat_count)

            # 如果翻译结果不含日文字符且没有重复，则退出循环
            if not contains_japanese_characters and not repeat_check:
                break

            # 如果翻译结果中包含日文字符或存在重复短语，则尝试下一个提示词
            if contains_japanese_characters or repeat_check:
                if contains_japanese_characters:
                    print("\033[31m检测到译文中包含日文字符，尝试使用下一个提示词进行翻译。\033[0m")
                if repeat_check:
                    print("\033[31m检测到译文中存在重复短语，调整参数并尝试下一个提示词。\033[0m")
                    model_params['frequency_penalty'] += 0.1
                continue

        # 如果所有提示词都尝试过仍未得到合格结果，使用最后一个翻译结果
        if translations is None:
            print("\033[31m所有提示词尝试失败，返回原始文本。\033[0m")
            translations = text

        # 打印翻译结果
        print(f"\033[36m[译文]\033[0m:\033[31m {translations}\033[0m")
        print("-------------------------------------------------------------------------------------------------------")

    except Exception as e:
        print(f"翻译处理失败：{e}")
        translations = text  # 返回原始文本

    return translations

# 定义处理翻译的路由
@app.route('/translate', methods=['GET'])
def translate():
    # 从GET请求中获取待翻译的文本
    text = request.args.get('text')
    print(f"\033[36m[原文]\033[0m \033[35m{text}\033[0m")
    # 检测text中是否包含"\n",如果包含则替换成\\n
    if '\n' in text:
        text = text.替换('\n'， '\\n')

    translation = handle_translation(text)

    if isinstance(translation, str):
        translation = translation.替换('\\n', '\n')
        return translation
    else:
        return translation, 500

# 还原代理设置
if original_http_proxy is not None:
    os.environ["http_proxy"] = original_http_proxy
if original_https_proxy is not 无:
    os.environ["https_proxy"] = original_https_proxy

def main():
    print("\033[31m服务器在 http://127.0.0.1:4000 上启动\033[0m")
    http_server = WSGIServer(('127.0.0.1', 4000), app, log=None, error_log=None)
    http_server.serve_forever()

if __name__ == '__main__':
    main()
