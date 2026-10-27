import random
import sys
from datetime import datetime, timedelta
from db import get_engine
from sqlalchemy import inspect, text

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def seed_demo_data():
    engine = get_engine()
    print("开始清空旧数据并重新生成 10 种商品的完整模拟经营数据...")

    with engine.begin() as conn:
        # 1. 清理演示与管理日志数据
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))
        existing_tables = {row[0] for row in conn.execute(text("SHOW TABLES")).all()}
        for table in ["audit_logs", "inventory_adjustments"]:
            if table in existing_tables:
                conn.execute(text(f"TRUNCATE TABLE {table};"))
        conn.execute(text("TRUNCATE TABLE sales_order_items;"))
        conn.execute(text("TRUNCATE TABLE sales_orders;"))
        conn.execute(text("TRUNCATE TABLE inventory;"))
        conn.execute(text("TRUNCATE TABLE products;"))
        conn.execute(text("TRUNCATE TABLE stores;"))
        if "managers" in existing_tables:
            conn.execute(text("TRUNCATE TABLE managers;"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))

        # 2. 写入经理和 3 家门店
        managers_data = [
            {"id": 1, "name": "张经理", "phone": None},
            {"id": 2, "name": "李经理", "phone": None},
            {"id": 3, "name": "王经理", "phone": None},
        ]
        if "managers" in existing_tables:
            conn.execute(
                text("INSERT INTO managers (id, name, phone) VALUES (:id, :name, :phone)"),
                managers_data,
            )
        stores_data = [
            {"id": 1, "name": "华东旗舰店", "city": "上海", "manager": "张经理", "manager_id": 1},
            {"id": 2, "name": "华南概念店", "city": "深圳", "manager": "李经理", "manager_id": 2},
            {"id": 3, "name": "北方直营店", "city": "北京", "manager": "王经理", "manager_id": 3},
        ]
        store_columns = {column["name"] for column in inspect(conn).get_columns("stores")}
        if "manager_id" in store_columns:
            conn.execute(
                text(
                    "INSERT INTO stores (id, name, city, manager, manager_id) "
                    "VALUES (:id, :name, :city, :manager, :manager_id)"
                ),
                stores_data,
            )
        else:
            conn.execute(
                text("INSERT INTO stores (id, name, city, manager) VALUES (:id, :name, :city, :manager)"),
                stores_data,
            )

        # 3. 写入 10 种商品 (包含成本价和售价)
        products_data = [
            {"id": 1, "sku": "SKU001", "name": "精品挂耳咖啡", "category": "饮品", "price": 68.00, "cost": 32.00},
            {"id": 2, "sku": "SKU002", "name": "保温随行杯", "category": "百货", "price": 129.00, "cost": 45.00},
            {"id": 3, "sku": "SKU003", "name": "全麦低卡吐司", "category": "烘焙", "price": 18.00, "cost": 8.00},
            {"id": 4, "sku": "SKU004", "name": "手冲咖啡壶套装", "category": "器具", "price": 299.00, "cost": 140.00},
            {"id": 5, "sku": "SKU005", "name": "燕麦奶1L装", "category": "饮品", "price": 28.00, "cost": 15.00},
            {"id": 6, "sku": "SKU006", "name": "冻干黑咖啡粉", "category": "饮品", "price": 45.00, "cost": 18.00},
            {"id": 7, "sku": "SKU007", "name": "双层隔热玻璃杯", "category": "百货", "price": 58.00, "cost": 22.00},
            {"id": 8, "sku": "SKU008", "name": "海盐黄油曲奇", "category": "烘焙", "price": 25.00, "cost": 10.00},
            {"id": 9, "sku": "SKU009", "name": "电动奶泡机", "category": "器具", "price": 89.00, "cost": 38.00},
            {"id": 10, "sku": "SKU010", "name": "冷萃咖啡浓缩液", "category": "饮品", "price": 36.00, "cost": 16.00},
        ]
        conn.execute(
            text("INSERT INTO products (id, sku, name, category, price, cost) VALUES (:id, :sku, :name, :category, :price, :cost)"),
            products_data,
        )

        # 4. 写入 30 条门店库存记录 (3 门店 × 10 商品，部分设置低库存以触发预警)
        inventory_data = []
        for s in stores_data:
            for p in products_data:
                stock_qty = random.choice([5, 8, 12, 22, 35, 48])
                inventory_data.append({
                    "store_id": s["id"],
                    "product_id": p["id"],
                    "quantity": stock_qty,
                    "safety_stock": 15,
                })
        conn.execute(
            text("INSERT INTO inventory (store_id, product_id, quantity, safety_stock) VALUES (:store_id, :product_id, :quantity, :safety_stock)"),
            inventory_data,
        )

        # 5. 生成 84 个订单，每个订单随机抽取 3~6 种商品生成明细
        today = datetime.now()
        orders_data = []
        items_data = []
        item_id_counter = 1

        for order_id in range(1, 85):
            store_id = random.choice([1, 2, 3])
            days_ago = random.randint(0, 28)
            order_date = (today - timedelta(days=days_ago)).strftime("%Y-%m-%d")
            order_no = f"ORD{today.strftime('%Y%m%d')}{order_id:04d}"

            order_total_amount = 0.0
            chosen_products = random.sample(products_data, random.randint(3, 6))

            for p in chosen_products:
                qty = random.randint(1, 3)
                unit_price = p["price"]
                subtotal = qty * unit_price
                order_total_amount += subtotal

                items_data.append({
                    "id": item_id_counter,
                    "order_id": order_id,
                    "product_id": p["id"],
                    "quantity": qty,
                    "unit_price": unit_price,
                    "subtotal": round(subtotal, 2),
                })
                item_id_counter += 1

            orders_data.append({
                "id": order_id,
                "order_no": order_no,
                "store_id": store_id,
                "total_amount": round(order_total_amount, 2),
                "order_date": order_date,
            })

        conn.execute(
            text("INSERT INTO sales_orders (id, order_no, store_id, total_amount, order_date) VALUES (:id, :order_no, :store_id, :total_amount, :order_date)"),
            orders_data,
        )
        conn.execute(
            text("INSERT INTO sales_order_items (id, order_id, product_id, quantity, unit_price, subtotal) VALUES (:id, :order_id, :product_id, :quantity, :unit_price, :subtotal)"),
            items_data,
        )

    print("[SUCCESS] 演示数据灌入完成：门店=3，商品=10，订单=84，库存=30。")


if __name__ == "__main__":
    seed_demo_data()
