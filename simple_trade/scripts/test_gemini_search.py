import time, os
from google import genai
from google.genai import types

API_KEY = 'AIzaSyC4e7kbq2AvTgdrqfPbOU0DkjV_TR5L8oo'
client = genai.Client(api_key=API_KEY)

prompt = (
    '请搜索港股 HK.02701（国民技术）最近3天的重要新闻和市场消息。'
    '用JSON返回：{"news":[{"title":"标题","date":"日期","summary":"摘要","sentiment":"positive/negative/neutral"}],'
    '"overall_sentiment":"总体情绪","key_catalysts":["催化剂"],"risk_factors":["风险"]}'
    '只返回JSON，不要其他文字。'
)

print("=== Gemini + Google Search grounding ===")
t0 = time.time()
try:
    r = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.2,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )
    )
    t1 = time.time()
    print(f"耗时: {t1-t0:.2f}秒")
    print(f"响应长度: {len(r.text)} 字符")
    print(r.text[:2000])
except Exception as e:
    t1 = time.time()
    print(f"失败 ({t1-t0:.2f}秒): {e}")
