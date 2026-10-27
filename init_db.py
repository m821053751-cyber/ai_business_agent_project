import os
import sys
import pymysql
import pymysql.constants.CLIENT as CLIENT
from dotenv import load_dotenv

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

load_dotenv()


def init_database() -> None:
    host = os.getenv("DB_HOST", "127.0.0.1")
    port = int(os.getenv("DB_PORT", "3306"))
    user = os.getenv("DB_USER", "root")
    password = os.getenv("DB_PASSWORD", "root")

    print(f"正在连接 MySQL 服务 ({host}:{port})...")
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        sql = f.read()

    conn = pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        client_flag=CLIENT.MULTI_STATEMENTS,
        charset="utf8mb4",
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql)
        conn.commit()
        print("[SUCCESS] 数据库 business_bi 与 8 张业务数据表初始化完成！")
    finally:
        conn.close()


if __name__ == "__main__":
    init_database()
