from openai import OpenAI
client = OpenAI(
api_key="sk-z7R2vzwYoNJEEkIfLIdRpw",
base_url="https://hubai.loe.gg/v1"
);

response = client.chat.completions.create(
model="deepseek-chat",
messages=[{"role": "user", "content": "Hello world"}]
#,stream=True
#,timeout=600
)
print(response.choices[0].message.content)
