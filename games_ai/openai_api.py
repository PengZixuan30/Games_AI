import os
from openai import OpenAI

def response_chat(model,url,message,tools,thinking="disabled"):

    client = OpenAI(
        api_key=os.environ.get('OPENAI_API_KEY'),
        base_url=url
    )
    
    response = client.chat.completions.create(
        model=model,
        messages=message,
        tools=tools,
        stream=False,
        extra_body={
            "thinking": {"type": thinking}
        },
    )

    return response.choices[0].message
