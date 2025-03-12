# CC98 Proxy

本项目基于 Fastapi 和 Httpx 实现了对 CC98 的反向代理和响应重写。

## 使用方法

在可访问 CC98 的机器中：

1. 安装 Python3
2. `pip install -r requirements.txt`
3. 设置环境变量（可选）
    - `HOST`: 服务监听的地址，默认为 `127.0.0.1`
    - `PORT`: 服务监听的端口，默认为 `8000`
    - `WORKERS`: 服务的工作进程数，默认为 `1`
4. 运行 `python main.py`

## 细节

本项目默认会把 `x.cc98.org` 代理到 `/proxy/x`，并对响应进行重写，以保证页面正常显示。例如：`api.cc98.org` 会被代理到 `/proxy/api`。

若需要使用自己的 api (`api.example.com`) 代理 `api.cc98.org`，请修改 `main.py` 中的 `TO_PROXY` 字典

```python
# 原来的配置
# TO_PROXY = {
#     "https://openid.cc98.org": "openid",
#     "https://api.cc98.org": "api",
#     "https://file.cc98.org": "file",
#     "https://gaming.cc98.org": "gaming",
#     "https://card.cc98.org": "card",
# }

# 修改后的配置
TO_PROXY = {
    "https://openid.cc98.org": "openid",
    "https://api.cc98.org": "https://api.example.com", # 务必包含协议头，路径重写会出问题
    "https://file.cc98.org": "file",
    "https://gaming.cc98.org": "gaming",
    "https://card.cc98.org": "card",
}
```