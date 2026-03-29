import os
from openai import OpenAI

def response_chat(model,url,message):

    client = OpenAI(
        api_key=os.environ.get('OPENAI_API_KEY'),
        base_url=url)
    
    response = client.chat.completions.create(
        model=model,
        messages=message,
        stream=False
    )

    return response.choices[0].message.content

if __name__ == "__main__":
    print("Test:\n")
    print(response_chat(model="deepseek-chat",message="test message"))
