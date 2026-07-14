import os
from openai import OpenAI

def response_chat(model,url,message,api_key,tools=[],thinking="disabled"):

    client = OpenAI(
        api_key=api_key,
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
