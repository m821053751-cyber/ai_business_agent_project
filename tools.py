from datetime import date, datetime, timedelta

from sqlalchemy import text


def _parse_date(value, default):
    """把 Agent 传入的日期规范化为 date；无法解析时给出明确错误。"""
    if value in (None, ""):
        return default
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"日期格式错误：{value!r}，请使用 YYYY-MM-DD") from exc

def sales_summary(engine, days=7):
    """统计最近 N 天已完成订单的订单数、销售额和毛利"""
    days = max(1, min(int(days), 90))  # 安全范围限制
    sql = text("""
        SELECT 
            COUNT(DISTINCT so.id) AS total_orders,
            COALESCE(SUM(soi.quantity), 0) AS total_units_sold,
            ROUND(COALESCE(SUM(soi.subtotal), 0), 2) AS total_revenue,
            ROUND(COALESCE(SUM(soi.subtotal - (soi.quantity * p.cost)), 0), 2) AS total_gross_profit
        FROM sales_orders so
        JOIN sales_order_items soi ON so.id = soi.order_id
        JOIN products p ON soi.product_id = p.id
        WHERE so.order_date >= DATE_SUB(CURDATE(), INTERVAL :days DAY)
    """)
    with engine.connect() as conn:
        result = conn.execute(sql, {"days": days}).mappings().first()
        return dict(result) if result else {}

def top_products(engine, days=7, limit=5):
    """按销量统计商品排行，并返回销量和销售额"""
    days = max(1, min(int(days), 90))
    limit = max(1, min(int(limit), 20))
    sql = text("""
        SELECT 
            p.name AS product_name,
            p.category,
            SUM(soi.quantity) AS total_sold,
            ROUND(SUM(soi.subtotal), 2) AS total_revenue
        FROM sales_order_items soi
        JOIN sales_orders so ON soi.order_id = so.id
        JOIN products p ON soi.product_id = p.id
        WHERE so.order_date >= DATE_SUB(CURDATE(), INTERVAL :days DAY)
        GROUP BY p.id, p.name, p.category
        ORDER BY total_sold DESC
        LIMIT :limit
    """)
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(sql, {"days": days, "limit": limit}).mappings().all()]

def low_stock(engine):
    """找出库存量小于或等于补货阈值的门店商品，并计算建议补货量"""
    sql = text("""
        SELECT 
            s.name AS store_name,
            p.name AS product_name,
            p.sku,
            i.quantity AS current_stock,
            i.safety_stock,
            GREATEST(i.safety_stock * 2 - i.quantity, 0) AS suggested_restock_qty
        FROM inventory i
        JOIN stores s ON i.store_id = s.id
        JOIN products p ON i.product_id = p.id
        WHERE i.quantity <= i.safety_stock
        ORDER BY i.quantity ASC
    """)
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(sql).mappings().all()]

def store_comparison(engine, days=7):
    """比较各门店的销售额、毛利和订单数"""
    days = max(1, min(int(days), 90))
    sql = text("""
        SELECT 
            s.name AS store_name,
            COUNT(DISTINCT so.id) AS total_orders,
            ROUND(COALESCE(SUM(soi.subtotal), 0), 2) AS total_revenue,
            ROUND(COALESCE(SUM(soi.subtotal - (soi.quantity * p.cost)), 0), 2) AS total_gross_profit
        FROM stores s
        LEFT JOIN sales_orders so ON s.id = so.store_id 
             AND so.order_date >= DATE_SUB(CURDATE(), INTERVAL :days DAY)
        LEFT JOIN sales_order_items soi ON so.id = soi.order_id
        LEFT JOIN products p ON soi.product_id = p.id
        GROUP BY s.id, s.name
        ORDER BY total_revenue DESC
    """)
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(sql, {"days": days}).mappings().all()]


def period_sales_detail(engine, start_date=None, end_date=None, store_name=None):
    """
    查询指定起止日期内的商品销售明细、周期汇总和相关门店负责人。

    start_date 与 end_date 均包含当天；未提供时默认查询最近 7 天。
    store_name 可按门店名称或城市进行模糊筛选。
    """
    today = date.today()
    start = _parse_date(start_date, today - timedelta(days=6))
    end = _parse_date(end_date, today)
    if end < start:
        raise ValueError("结束日期不能早于开始日期")
    if (end - start).days > 366:
        raise ValueError("单次查询范围不能超过 367 天")

    end_exclusive = end + timedelta(days=1)
    store_filter = (str(store_name).strip() if store_name is not None else "")
    joins = """
        FROM sales_orders so
        JOIN sales_order_items soi ON so.id = soi.order_id
        JOIN products p ON soi.product_id = p.id
        JOIN stores s ON so.store_id = s.id
    """
    params = {"start_date": start, "end_date": end_exclusive}
    where = ["so.order_date >= :start_date", "so.order_date < :end_date"]
    if store_filter:
        where.append("(s.name LIKE :store_filter OR s.city LIKE :store_filter)")
        params["store_filter"] = f"%{store_filter}%"
    where_sql = " AND ".join(where)

    totals_sql = text(f"""
        SELECT
            COUNT(DISTINCT so.id) AS total_orders,
            COUNT(DISTINCT soi.product_id) AS products_sold,
            COALESCE(SUM(soi.quantity), 0) AS total_units_sold,
            ROUND(COALESCE(SUM(soi.subtotal), 0), 2) AS total_revenue,
            ROUND(COALESCE(SUM(soi.subtotal - (soi.quantity * p.cost)), 0), 2) AS total_gross_profit
        {joins}
        WHERE {where_sql}
    """)
    products_sql = text(f"""
        SELECT
            p.name AS product_name,
            p.category,
            COUNT(DISTINCT so.id) AS order_count,
            SUM(soi.quantity) AS total_units_sold,
            ROUND(SUM(soi.subtotal), 2) AS total_revenue,
            ROUND(SUM(soi.subtotal - (soi.quantity * p.cost)), 2) AS total_gross_profit
        {joins}
        WHERE {where_sql}
        GROUP BY p.id, p.name, p.category
        ORDER BY total_units_sold DESC, total_revenue DESC
    """)

    store_where = ""
    if store_filter:
        store_where = "WHERE s.name LIKE :store_filter OR s.city LIKE :store_filter"
    stores_sql = text(f"""
        SELECT
            s.name AS store_name,
            s.city,
            COALESCE(m.name, s.manager) AS manager,
            COUNT(DISTINCT so.id) AS total_orders,
            COALESCE(SUM(soi.quantity), 0) AS total_units_sold,
            ROUND(COALESCE(SUM(soi.subtotal), 0), 2) AS total_revenue,
            ROUND(COALESCE(SUM(soi.subtotal - (soi.quantity * p.cost)), 0), 2) AS total_gross_profit
        FROM stores s
        LEFT JOIN managers m ON m.id = s.manager_id
        LEFT JOIN sales_orders so
            ON s.id = so.store_id
            AND so.order_date >= :start_date
            AND so.order_date < :end_date
        LEFT JOIN sales_order_items soi ON so.id = soi.order_id
        LEFT JOIN products p ON soi.product_id = p.id
        {store_where}
        GROUP BY s.id, s.name, s.city, s.manager, m.id, m.name
        ORDER BY total_revenue DESC, s.name
    """)

    with engine.connect() as conn:
        totals_row = conn.execute(totals_sql, params).mappings().first() or {}
        product_rows = conn.execute(products_sql, params).mappings().all()
        store_rows = conn.execute(stores_sql, params).mappings().all()

    total_revenue = float(totals_row.get("total_revenue") or 0)
    total_gross_profit = float(totals_row.get("total_gross_profit") or 0)
    products = []
    for row in product_rows:
        item = dict(row)
        revenue = float(item.get("total_revenue") or 0)
        profit = float(item.get("total_gross_profit") or 0)
        item["total_units_sold"] = int(item.get("total_units_sold") or 0)
        item["order_count"] = int(item.get("order_count") or 0)
        item["total_revenue"] = revenue
        item["total_gross_profit"] = profit
        item["gross_margin_percent"] = round(profit / revenue * 100, 2) if revenue else 0.0
        products.append(item)

    stores = []
    for row in store_rows:
        item = dict(row)
        item["manager"] = item.get("manager") or "未设置负责人"
        item["total_orders"] = int(item.get("total_orders") or 0)
        item["total_units_sold"] = int(item.get("total_units_sold") or 0)
        item["total_revenue"] = float(item.get("total_revenue") or 0)
        item["total_gross_profit"] = float(item.get("total_gross_profit") or 0)
        stores.append(item)

    return {
        "period": {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "days": (end - start).days + 1,
            "store_filter": store_filter or None,
        },
        "totals": {
            "total_orders": int(totals_row.get("total_orders") or 0),
            "products_sold": int(totals_row.get("products_sold") or 0),
            "total_units_sold": int(totals_row.get("total_units_sold") or 0),
            "total_revenue": total_revenue,
            "total_gross_profit": total_gross_profit,
            "gross_margin_percent": round(total_gross_profit / total_revenue * 100, 2) if total_revenue else 0.0,
        },
        "products": products,
        "stores": stores,
    }

# 工具白名单与定义（OpenAI Function Calling 格式）
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "sales_summary",
            "description": "统计最近 N 天的订单数、销售额和毛利",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "天数周期，默认 7"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "top_products",
            "description": "按销量查询畅销商品排行榜",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "天数周期，默认 7"},
                    "limit": {"type": "integer", "description": "返回商品数量，默认 5"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "low_stock",
            "description": "查询门店库存不足（小于等于安全阈值）的商品及建议补货量",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "store_comparison",
            "description": "对比各门店在最近 N 天的销售额、毛利和订单数表现",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "天数周期，默认 7"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "period_sales_detail",
            "description": (
                "按明确的起止日期查询销售明细，返回商品销量、销售额、毛利、周期总计，"
                "以及匹配门店的负责人。日期格式为 YYYY-MM-DD，结束日期包含当天。"
                "如果只查询门店负责人，可以不传日期，此时默认查询最近 7 天的销售。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "开始日期 YYYY-MM-DD，包含当天；默认 7 天前"},
                    "end_date": {"type": "string", "description": "结束日期 YYYY-MM-DD，包含当天；默认今天"},
                    "store_name": {"type": "string", "description": "可选，按门店名称或城市筛选"}
                }
            }
        }
    }
]

TOOL_REGISTRY = {
    "sales_summary": sales_summary,
    "top_products": top_products,
    "low_stock": low_stock,
    "store_comparison": store_comparison,
    "period_sales_detail": period_sales_detail
}
