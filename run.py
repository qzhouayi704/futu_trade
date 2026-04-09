#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
富途量化交易系统启动脚本 - FastAPI 版本
"""

import sys
import os
import argparse

# 确保项目根目录在Python路径中
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 加载 .env 文件到环境变量
from dotenv import load_dotenv
load_dotenv(os.path.join(project_root, '.env'))


def main():
    """启动 FastAPI 应用"""
    parser = argparse.ArgumentParser(description='富途量化交易系统 - FastAPI 服务器')
    parser.add_argument('--host', default='0.0.0.0', help='服务器地址')
    parser.add_argument('--port', type=int, default=5001, help='服务器端口')
    parser.add_argument('--reload', action='store_true', help='启用热重载')
    args = parser.parse_args()

    # 使用 uvicorn 启动 FastAPI 应用
    import uvicorn
    uvicorn.run(
        "simple_trade.asgi:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="warning",
        access_log=False
    )


if __name__ == '__main__':
    main()


