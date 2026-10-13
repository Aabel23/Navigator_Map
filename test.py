import requests

url = "http://127.0.0.1:8000/api/tms/v1/stations"

r = requests.get(url, timeout=10)

print(r.status_code)
print(r.text)