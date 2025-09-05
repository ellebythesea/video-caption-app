import base64
with open('credentials.json', 'rb') as f:
    print(base64.b64encode(f.read()).decode())