# XUnity.AutoTranslator-chatgpt
# 修改代码中api参数
**OpenAI API 配置参数**  
Base_url = "https://api.sweetyun.com"   # 中转请求地址  
Model_Type = "gpt-4-0125-preview"   # 模型类型  
API_key = "sk-1111111111111111111111111111111"   # API密钥  
Proxy_port = ""   # 代理端口，如果不使用代理则为空  

<b>更改XUnity.AutoTranslator插件的AutoTranslatorConfig.ini或者Config.ini文件</b>

[Service]  
Endpoint=CustomTranslate  
FallbackEndpoint=  

[General]  
Language=zh        
FromLanguage=ja  
..............  
[Custom]  
Url=http://127.0.0.1:4000/translate  
