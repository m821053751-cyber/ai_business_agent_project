"""Transactional administration service for business master data.

The Streamlit AI assistant only consumes the read-only functions in tools.py.
All writes go through this module and are recorded in the audit trail.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import inspect, text


ACTIVE = "active"
INACTIVE = "inactive"
VALID_STATUSES = {ACTIVE, INACTIVE}


class ManagementError(Exception):
    """Base class for expected management operations errors."""


class ValidationError(ManagementError):
    pass


class NotFoundError(ManagementError):
    pass


class ConflictError(ManagementError):
    pass


def _is_mysql(engine: Any) -> bool:
    return engine.dialect.name == "mysql"


def _table_exists(conn: Any, table_name: str) -> bool:
    return table_name in inspect(conn).get_table_names()


def _column_names(conn: Any, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(conn).get_columns(table_name)}


def _column_max_length(conn: Any, table_name: str, column_name: str) -> int | None:
    for column in inspect(conn).get_columns(table_name):
        if column["name"] == column_name:
            length = getattr(column["type"], "length", None)
            return int(length) if length is not None else None
    return None


def _index_names(conn: Any, table_name: str) -> set[str]:
    return {index["name"] for index in inspect(conn).get_indexes(table_name)}


def _foreign_key_exists(conn: Any, table_name: str, column_name: str, referred_table: str) -> bool:
    for foreign_key in inspect(conn).get_foreign_keys(table_name):
        if (
            foreign_key.get("referred_table") == referred_table
            and column_name in foreign_key.get("constrained_columns", [])
        ):
            return True
    return False


def _ensure_transactional_engines(engine: Any, conn: Any) -> None:
    """Convert legacy MyISAM business tables to InnoDB without changing data."""
    if not _is_mysql(engine):
        return
    engines = {
        row["TABLE_NAME"]: row["ENGINE"]
        for row in conn.execute(
            text(
                "SELECT TABLE_NAME, ENGINE FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = DATABASE()"
            )
        ).mappings().all()
    }
    for table_name in (
        "stores",
        "products",
        "inventory",
        "sales_orders",
        "sales_order_items",
    ):
        if engines.get(table_name) and engines[table_name].lower() != "innodb":
            conn.execute(text(f"ALTER TABLE {table_name} ENGINE=InnoDB"))


def _create_managers_table(engine: Any) -> str:
    if _is_mysql(engine):
        return """
            CREATE TABLE IF NOT EXISTS managers (
                id INTEGER PRIMARY KEY AUTO_INCREMENT,
                name VARCHAR(100) NOT NULL,
                phone VARCHAR(30) NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uniq_manager_name (name)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    return """
        CREATE TABLE IF NOT EXISTS managers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(100) NOT NULL,
            phone VARCHAR(30) NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (name)
        )
    """


def _create_inventory_adjustments_table(engine: Any) -> str:
    if _is_mysql(engine):
        return """
            CREATE TABLE IF NOT EXISTS inventory_adjustments (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                inventory_id INTEGER NOT NULL,
                store_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                before_quantity INTEGER NOT NULL,
                after_quantity INTEGER NOT NULL,
                delta INTEGER NOT NULL,
                reason VARCHAR(255) NOT NULL,
                operator VARCHAR(100) NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_adjustment_inventory FOREIGN KEY (inventory_id) REFERENCES inventory(id),
                CONSTRAINT fk_adjustment_store FOREIGN KEY (store_id) REFERENCES stores(id),
                CONSTRAINT fk_adjustment_product FOREIGN KEY (product_id) REFERENCES products(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    return """
        CREATE TABLE IF NOT EXISTS inventory_adjustments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inventory_id INTEGER NOT NULL,
            store_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            before_quantity INTEGER NOT NULL,
            after_quantity INTEGER NOT NULL,
            delta INTEGER NOT NULL,
            reason VARCHAR(255) NOT NULL,
            operator VARCHAR(100) NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """


def _create_audit_logs_table(engine: Any) -> str:
    if _is_mysql(engine):
        return """
            CREATE TABLE IF NOT EXISTS audit_logs (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                operator VARCHAR(100) NOT NULL,
                action VARCHAR(80) NOT NULL,
                entity_type VARCHAR(40) NOT NULL,
                entity_id INTEGER NOT NULL,
                before_data TEXT NULL,
                after_data TEXT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    return """
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operator VARCHAR(100) NOT NULL,
            action VARCHAR(80) NOT NULL,
            entity_type VARCHAR(40) NOT NULL,
            entity_id INTEGER NOT NULL,
            before_data TEXT NULL,
            after_data TEXT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """


def ensure_management_schema(engine: Any) -> None:
    """Create or upgrade the management schema idempotently."""
    with engine.begin() as conn:
        if not _table_exists(conn, "managers"):
            conn.execute(text(_create_managers_table(engine)))

        # Existing demo databases may use MyISAM. Transactional writes and the
        # new foreign keys require InnoDB, so the migration preserves data while
        # changing only the storage engine for the core business tables.
        _ensure_transactional_engines(engine, conn)

        store_columns = _column_names(conn, "stores")
        if "manager_id" not in store_columns:
            conn.execute(text("ALTER TABLE stores ADD COLUMN manager_id INTEGER NULL"))
        if _is_mysql(engine) and (manager_length := _column_max_length(conn, "stores", "manager")) is not None:
            if manager_length < 100:
                conn.execute(text("ALTER TABLE stores MODIFY COLUMN manager VARCHAR(100) NULL"))
        if "status" not in store_columns:
            conn.execute(text("ALTER TABLE stores ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'active'"))
        if "updated_at" not in store_columns:
            if _is_mysql(engine):
                conn.execute(
                    text(
                        "ALTER TABLE stores ADD COLUMN updated_at TIMESTAMP NOT NULL "
                        "DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"
                    )
                )
            else:
                conn.execute(text("ALTER TABLE stores ADD COLUMN updated_at TIMESTAMP NULL"))

        product_columns = _column_names(conn, "products")
        if "status" not in product_columns:
            conn.execute(text("ALTER TABLE products ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'active'"))
        if "updated_at" not in product_columns:
            if _is_mysql(engine):
                conn.execute(
                    text(
                        "ALTER TABLE products ADD COLUMN updated_at TIMESTAMP NOT NULL "
                        "DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"
                    )
                )
            else:
                conn.execute(text("ALTER TABLE products ADD COLUMN updated_at TIMESTAMP NULL"))

        conn.execute(text("UPDATE stores SET status = 'active' WHERE status IS NULL OR status = ''"))
        conn.execute(text("UPDATE products SET status = 'active' WHERE status IS NULL OR status = ''"))

        manager_names = conn.execute(
            text(
                "SELECT DISTINCT TRIM(manager) FROM stores "
                "WHERE manager IS NOT NULL AND TRIM(manager) <> ''"
            )
        ).scalars().all()
        for manager_name in manager_names:
            exists = conn.execute(
                text("SELECT id FROM managers WHERE LOWER(name) = LOWER(:name) LIMIT 1"),
                {"name": manager_name},
            ).scalar()
            if exists is None:
                conn.execute(
                    text("INSERT INTO managers (name, status) VALUES (:name, 'active')"),
                    {"name": manager_name},
                )

        conn.execute(
            text(
                "UPDATE stores SET manager_id = ("
                "SELECT managers.id FROM managers "
                "WHERE LOWER(managers.name) = LOWER(TRIM(stores.manager))"
                ") WHERE manager_id IS NULL AND manager IS NOT NULL AND TRIM(manager) <> ''"
            )
        )

        if not _table_exists(conn, "inventory_adjustments"):
            conn.execute(text(_create_inventory_adjustments_table(engine)))
        if not _table_exists(conn, "audit_logs"):
            conn.execute(text(_create_audit_logs_table(engine)))

        if _is_mysql(engine):
            store_indexes = _index_names(conn, "stores")
            if "idx_stores_manager" not in store_indexes:
                conn.execute(text("CREATE INDEX idx_stores_manager ON stores(manager_id)"))
            if "idx_stores_status" not in store_indexes:
                conn.execute(text("CREATE INDEX idx_stores_status ON stores(status)"))
            if not _foreign_key_exists(conn, "stores", "manager_id", "managers"):
                conn.execute(
                    text(
                        "ALTER TABLE stores ADD CONSTRAINT fk_stores_manager "
                        "FOREIGN KEY (manager_id) REFERENCES managers(id)"
                    )
                )

            product_indexes = _index_names(conn, "products")
            if "idx_products_status" not in product_indexes:
                conn.execute(text("CREATE INDEX idx_products_status ON products(status)"))

            adjustment_indexes = _index_names(conn, "inventory_adjustments")
            if "idx_adjustments_created" not in adjustment_indexes:
                conn.execute(
                    text("CREATE INDEX idx_adjustments_created ON inventory_adjustments(created_at)")
                )

            audit_indexes = _index_names(conn, "audit_logs")
            if "idx_audit_created" not in audit_indexes:
                conn.execute(text("CREATE INDEX idx_audit_created ON audit_logs(created_at)"))


def _clean_required(value: Any, label: str, max_length: int) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValidationError(f"{label}不能为空")
    if len(cleaned) > max_length:
        raise ValidationError(f"{label}不能超过 {max_length} 个字符")
    return cleaned


def _clean_optional(value: Any, label: str, max_length: int) -> str | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    if len(cleaned) > max_length:
        raise ValidationError(f"{label}不能超过 {max_length} 个字符")
    return cleaned


def _clean_operator(operator: Any) -> str:
    return _clean_required(operator, "操作人", 100)


def _clean_status(status: Any) -> str:
    cleaned = str(status or "").strip().lower()
    if cleaned not in VALID_STATUSES:
        raise ValidationError("状态必须是 active 或 inactive")
    return cleaned


def _money(value: Any, label: str) -> float:
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(f"{label}必须是有效金额") from exc
    if not amount.is_finite():
        raise ValidationError(f"{label}必须是有效金额")
    if amount < 0:
        raise ValidationError(f"{label}不能为负数")
    return float(amount)


def _integer(value: Any, label: str, minimum: int = 0) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label}必须是整数") from exc
    if number < minimum:
        raise ValidationError(f"{label}不能小于 {minimum}")
    return number


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _row_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    for key, value in list(result.items()):
        if isinstance(value, Decimal):
            result[key] = float(value)
    return result


def _get_entity(conn: Any, table: str, entity_id: int, lock: bool = False) -> dict[str, Any]:
    suffix = " FOR UPDATE" if lock and conn.dialect.name == "mysql" else ""
    row = conn.execute(
        text(f"SELECT * FROM {table} WHERE id = :entity_id{suffix}"),
        {"entity_id": entity_id},
    ).mappings().first()
    if row is None:
        raise NotFoundError(f"{table} 记录不存在")
    return _row_dict(row) or {}


def _ensure_unique(
    conn: Any,
    table: str,
    column: str,
    value: str,
    label: str,
    exclude_id: int | None = None,
) -> None:
    sql = f"SELECT id FROM {table} WHERE LOWER({column}) = LOWER(:value)"
    params: dict[str, Any] = {"value": value}
    if exclude_id is not None:
        sql += " AND id <> :exclude_id"
        params["exclude_id"] = exclude_id
    if conn.execute(text(sql + " LIMIT 1"), params).scalar() is not None:
        raise ConflictError(f"{label}已存在")


def _write_audit(
    conn: Any,
    operator: str,
    action: str,
    entity_type: str,
    entity_id: int,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> None:
    conn.execute(
        text(
            "INSERT INTO audit_logs "
            "(operator, action, entity_type, entity_id, before_data, after_data) "
            "VALUES (:operator, :action, :entity_type, :entity_id, :before_data, :after_data)"
        ),
        {
            "operator": operator,
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "before_data": (
                json.dumps(_json_safe(before), ensure_ascii=False, sort_keys=True)
                if before is not None
                else None
            ),
            "after_data": (
                json.dumps(_json_safe(after), ensure_ascii=False, sort_keys=True)
                if after is not None
                else None
            ),
        },
    )


def _manager_status(conn: Any, manager_id: int | None) -> dict[str, Any] | None:
    if manager_id is None:
        return None
    manager = _get_entity(conn, "managers", manager_id)
    if manager["status"] != ACTIVE:
        raise ConflictError("所选经理已停用，不能分配或继续使用")
    return manager


def list_products(engine: Any, include_inactive: bool = True) -> list[dict[str, Any]]:
    where = "" if include_inactive else "WHERE status = 'active'"
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, sku, name, category, price, cost, status, created_at, updated_at "
                f"FROM products {where} ORDER BY status, name, sku"
            )
        ).mappings().all()
    return [_row_dict(row) or {} for row in rows]


def list_managers(engine: Any, include_inactive: bool = True) -> list[dict[str, Any]]:
    where = "" if include_inactive else "WHERE m.status = 'active'"
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT m.id, m.name, m.phone, m.status, m.created_at, m.updated_at, "
                "COUNT(s.id) AS assigned_store_count "
                "FROM managers m LEFT JOIN stores s ON s.manager_id = m.id "
                f"{where} GROUP BY m.id, m.name, m.phone, m.status, m.created_at, m.updated_at "
                "ORDER BY m.status, m.name"
            )
        ).mappings().all()
    return [_row_dict(row) or {} for row in rows]


def list_stores(engine: Any, include_inactive: bool = True) -> list[dict[str, Any]]:
    where = "" if include_inactive else "WHERE s.status = 'active'"
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT s.id, s.name, s.city, s.manager_id, s.status, s.created_at, s.updated_at, "
                "COALESCE(m.name, s.manager) AS manager_name, m.phone AS manager_phone "
                "FROM stores s LEFT JOIN managers m ON m.id = s.manager_id "
                f"{where} ORDER BY s.status, s.name"
            )
        ).mappings().all()
    return [_row_dict(row) or {} for row in rows]


def list_inventory(engine: Any) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT i.id, i.store_id, i.product_id, i.quantity, i.safety_stock, i.updated_at, "
                "s.name AS store_name, s.status AS store_status, "
                "p.sku, p.name AS product_name, p.status AS product_status "
                "FROM inventory i "
                "JOIN stores s ON s.id = i.store_id "
                "JOIN products p ON p.id = i.product_id "
                "ORDER BY s.name, p.name"
            )
        ).mappings().all()
    return [_row_dict(row) or {} for row in rows]


def list_audit_logs(engine: Any, limit: int = 200) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 1000))
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, operator, action, entity_type, entity_id, before_data, after_data, created_at "
                "FROM audit_logs ORDER BY id DESC LIMIT :limit"
            ),
            {"limit": safe_limit},
        ).mappings().all()
    result = []
    for row in rows:
        item = _row_dict(row) or {}
        for key in ("before_data", "after_data"):
            if item.get(key):
                try:
                    item[key] = json.loads(item[key])
                except (TypeError, ValueError):
                    pass
        result.append(item)
    return result


def list_inventory_adjustments(engine: Any, limit: int = 200) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 1000))
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT a.id, a.inventory_id, a.store_id, a.product_id, "
                "a.before_quantity, a.after_quantity, a.delta, a.reason, a.operator, a.created_at, "
                "s.name AS store_name, p.name AS product_name "
                "FROM inventory_adjustments a "
                "JOIN stores s ON s.id = a.store_id "
                "JOIN products p ON p.id = a.product_id "
                "ORDER BY a.id DESC LIMIT :limit"
            ),
            {"limit": safe_limit},
        ).mappings().all()
    return [_row_dict(row) or {} for row in rows]


def create_product(
    engine: Any,
    operator: str,
    sku: str,
    name: str,
    category: str,
    price: Any,
    cost: Any,
) -> dict[str, Any]:
    actor = _clean_operator(operator)
    values = {
        "sku": _clean_required(sku, "SKU", 50),
        "name": _clean_required(name, "商品名称", 100),
        "category": _clean_required(category, "商品分类", 50),
        "price": _money(price, "售价"),
        "cost": _money(cost, "成本"),
    }
    with engine.begin() as conn:
        _ensure_unique(conn, "products", "sku", values["sku"], "SKU")
        result = conn.execute(
            text(
                "INSERT INTO products (sku, name, category, price, cost, status) "
                "VALUES (:sku, :name, :category, :price, :cost, 'active')"
            ),
            values,
        )
        product_id = int(result.lastrowid)
        after = _get_entity(conn, "products", product_id)
        _write_audit(conn, actor, "product.create", "product", product_id, None, after)
    return after


def update_product(
    engine: Any,
    operator: str,
    product_id: int,
    sku: str,
    name: str,
    category: str,
    price: Any,
    cost: Any,
) -> dict[str, Any]:
    actor = _clean_operator(operator)
    entity_id = _integer(product_id, "商品 ID", 1)
    values = {
        "sku": _clean_required(sku, "SKU", 50),
        "name": _clean_required(name, "商品名称", 100),
        "category": _clean_required(category, "商品分类", 50),
        "price": _money(price, "售价"),
        "cost": _money(cost, "成本"),
    }
    with engine.begin() as conn:
        before = _get_entity(conn, "products", entity_id, lock=True)
        _ensure_unique(conn, "products", "sku", values["sku"], "SKU", exclude_id=entity_id)
        conn.execute(
            text(
                "UPDATE products SET sku = :sku, name = :name, category = :category, "
                "price = :price, cost = :cost, updated_at = CURRENT_TIMESTAMP WHERE id = :entity_id"
            ),
            {**values, "entity_id": entity_id},
        )
        after = _get_entity(conn, "products", entity_id)
        _write_audit(conn, actor, "product.update", "product", entity_id, before, after)
    return after


def set_product_status(engine: Any, operator: str, product_id: int, active: bool) -> dict[str, Any]:
    actor = _clean_operator(operator)
    entity_id = _integer(product_id, "商品 ID", 1)
    target_status = ACTIVE if active else INACTIVE
    with engine.begin() as conn:
        before = _get_entity(conn, "products", entity_id, lock=True)
        if before["status"] == target_status:
            return before
        if target_status == INACTIVE:
            stock = conn.execute(
                text("SELECT COALESCE(SUM(quantity), 0) FROM inventory WHERE product_id = :product_id"),
                {"product_id": entity_id},
            ).scalar()
            if int(stock or 0) > 0:
                raise ConflictError("该商品仍有库存，请先将各门店库存调整为 0 再停用")
        conn.execute(
            text("UPDATE products SET status = :status, updated_at = CURRENT_TIMESTAMP WHERE id = :entity_id"),
            {"status": target_status, "entity_id": entity_id},
        )
        after = _get_entity(conn, "products", entity_id)
        action = "product.activate" if active else "product.deactivate"
        _write_audit(conn, actor, action, "product", entity_id, before, after)
    return after


def create_manager(engine: Any, operator: str, name: str, phone: str | None = None) -> dict[str, Any]:
    actor = _clean_operator(operator)
    values = {
        "name": _clean_required(name, "经理姓名", 100),
        "phone": _clean_optional(phone, "联系电话", 30),
    }
    with engine.begin() as conn:
        _ensure_unique(conn, "managers", "name", values["name"], "经理姓名")
        result = conn.execute(
            text(
                "INSERT INTO managers (name, phone, status) "
                "VALUES (:name, :phone, 'active')"
            ),
            values,
        )
        manager_id = int(result.lastrowid)
        after = _get_entity(conn, "managers", manager_id)
        _write_audit(conn, actor, "manager.create", "manager", manager_id, None, after)
    return after


def update_manager(
    engine: Any,
    operator: str,
    manager_id: int,
    name: str,
    phone: str | None = None,
) -> dict[str, Any]:
    actor = _clean_operator(operator)
    entity_id = _integer(manager_id, "经理 ID", 1)
    values = {
        "name": _clean_required(name, "经理姓名", 100),
        "phone": _clean_optional(phone, "联系电话", 30),
    }
    with engine.begin() as conn:
        before = _get_entity(conn, "managers", entity_id, lock=True)
        _ensure_unique(conn, "managers", "name", values["name"], "经理姓名", exclude_id=entity_id)
        conn.execute(
            text(
                "UPDATE managers SET name = :name, phone = :phone, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = :entity_id"
            ),
            {**values, "entity_id": entity_id},
        )
        conn.execute(
            text("UPDATE stores SET manager = :name WHERE manager_id = :entity_id"),
            {"name": values["name"], "entity_id": entity_id},
        )
        after = _get_entity(conn, "managers", entity_id)
        _write_audit(conn, actor, "manager.update", "manager", entity_id, before, after)
    return after


def set_manager_status(engine: Any, operator: str, manager_id: int, active: bool) -> dict[str, Any]:
    actor = _clean_operator(operator)
    entity_id = _integer(manager_id, "经理 ID", 1)
    target_status = ACTIVE if active else INACTIVE
    with engine.begin() as conn:
        before = _get_entity(conn, "managers", entity_id, lock=True)
        if before["status"] == target_status:
            return before
        if target_status == INACTIVE:
            assigned = conn.execute(
                text(
                    "SELECT COUNT(*) FROM stores "
                    "WHERE manager_id = :manager_id AND status = 'active'"
                ),
                {"manager_id": entity_id},
            ).scalar()
            if int(assigned or 0) > 0:
                raise ConflictError("该经理仍负责在营门店，请先在门店页改派负责人")
        conn.execute(
            text("UPDATE managers SET status = :status, updated_at = CURRENT_TIMESTAMP WHERE id = :entity_id"),
            {"status": target_status, "entity_id": entity_id},
        )
        after = _get_entity(conn, "managers", entity_id)
        action = "manager.activate" if active else "manager.deactivate"
        _write_audit(conn, actor, action, "manager", entity_id, before, after)
    return after


def create_store(
    engine: Any,
    operator: str,
    name: str,
    city: str,
    manager_id: int | None = None,
) -> dict[str, Any]:
    actor = _clean_operator(operator)
    values = {
        "name": _clean_required(name, "门店名称", 100),
        "city": _clean_required(city, "城市", 50),
    }
    normalized_manager_id = (
        _integer(manager_id, "经理 ID", 1) if manager_id not in (None, "") else None
    )
    with engine.begin() as conn:
        _ensure_unique(conn, "stores", "name", values["name"], "门店名称")
        manager = _manager_status(conn, normalized_manager_id)
        values["manager_id"] = normalized_manager_id
        values["manager"] = manager["name"] if manager else None
        result = conn.execute(
            text(
                "INSERT INTO stores (name, city, manager_id, manager, status) "
                "VALUES (:name, :city, :manager_id, :manager, 'active')"
            ),
            values,
        )
        store_id = int(result.lastrowid)
        after = _get_entity(conn, "stores", store_id)
        _write_audit(conn, actor, "store.create", "store", store_id, None, after)
    return after


def update_store(
    engine: Any,
    operator: str,
    store_id: int,
    name: str,
    city: str,
    manager_id: int | None = None,
) -> dict[str, Any]:
    actor = _clean_operator(operator)
    entity_id = _integer(store_id, "门店 ID", 1)
    values = {
        "name": _clean_required(name, "门店名称", 100),
        "city": _clean_required(city, "城市", 50),
    }
    normalized_manager_id = (
        _integer(manager_id, "经理 ID", 1) if manager_id not in (None, "") else None
    )
    with engine.begin() as conn:
        before = _get_entity(conn, "stores", entity_id, lock=True)
        _ensure_unique(conn, "stores", "name", values["name"], "门店名称", exclude_id=entity_id)
        manager = _manager_status(conn, normalized_manager_id)
        values["manager_id"] = normalized_manager_id
        values["manager"] = manager["name"] if manager else None
        conn.execute(
            text(
                "UPDATE stores SET name = :name, city = :city, manager_id = :manager_id, "
                "manager = :manager, updated_at = CURRENT_TIMESTAMP WHERE id = :entity_id"
            ),
            {**values, "entity_id": entity_id},
        )
        after = _get_entity(conn, "stores", entity_id)
        _write_audit(conn, actor, "store.update", "store", entity_id, before, after)
    return after


def set_store_status(engine: Any, operator: str, store_id: int, active: bool) -> dict[str, Any]:
    actor = _clean_operator(operator)
    entity_id = _integer(store_id, "门店 ID", 1)
    target_status = ACTIVE if active else INACTIVE
    with engine.begin() as conn:
        before = _get_entity(conn, "stores", entity_id, lock=True)
        if before["status"] == target_status:
            return before
        if target_status == INACTIVE:
            stock = conn.execute(
                text("SELECT COALESCE(SUM(quantity), 0) FROM inventory WHERE store_id = :store_id"),
                {"store_id": entity_id},
            ).scalar()
            if int(stock or 0) > 0:
                raise ConflictError("该门店仍有库存，请先将门店库存调整为 0 再停用")
        conn.execute(
            text("UPDATE stores SET status = :status, updated_at = CURRENT_TIMESTAMP WHERE id = :entity_id"),
            {"status": target_status, "entity_id": entity_id},
        )
        after = _get_entity(conn, "stores", entity_id)
        action = "store.activate" if active else "store.deactivate"
        _write_audit(conn, actor, action, "store", entity_id, before, after)
    return after


def upsert_inventory(
    engine: Any,
    operator: str,
    store_id: int,
    product_id: int,
    quantity: Any,
    safety_stock: Any,
    reason: str,
) -> dict[str, Any]:
    actor = _clean_operator(operator)
    normalized_store_id = _integer(store_id, "门店 ID", 1)
    normalized_product_id = _integer(product_id, "商品 ID", 1)
    new_quantity = _integer(quantity, "库存数量")
    new_safety_stock = _integer(safety_stock, "补货阈值")
    adjustment_reason = _clean_required(reason, "调整原因", 255)

    with engine.begin() as conn:
        store = _get_entity(conn, "stores", normalized_store_id, lock=True)
        product = _get_entity(conn, "products", normalized_product_id, lock=True)
        if store["status"] != ACTIVE:
            raise ConflictError("停用门店不能新增或调整库存")
        if product["status"] != ACTIVE:
            raise ConflictError("停用商品不能新增或调整库存")

        suffix = " FOR UPDATE" if conn.dialect.name == "mysql" else ""
        existing_row = conn.execute(
            text(
                "SELECT * FROM inventory "
                f"WHERE store_id = :store_id AND product_id = :product_id{suffix}"
            ),
            {"store_id": normalized_store_id, "product_id": normalized_product_id},
        ).mappings().first()

        if existing_row is None:
            result = conn.execute(
                text(
                    "INSERT INTO inventory (store_id, product_id, quantity, safety_stock) "
                    "VALUES (:store_id, :product_id, :quantity, :safety_stock)"
                ),
                {
                    "store_id": normalized_store_id,
                    "product_id": normalized_product_id,
                    "quantity": new_quantity,
                    "safety_stock": new_safety_stock,
                },
            )
            inventory_id = int(result.lastrowid)
            before = None
            action = "inventory.create"
        else:
            before = _row_dict(existing_row) or {}
            inventory_id = int(before["id"])
            if int(before["quantity"]) == new_quantity and int(before["safety_stock"]) == new_safety_stock:
                return before
            conn.execute(
                text(
                    "UPDATE inventory SET quantity = :quantity, safety_stock = :safety_stock, "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = :inventory_id"
                ),
                {
                    "quantity": new_quantity,
                    "safety_stock": new_safety_stock,
                    "inventory_id": inventory_id,
                },
            )
            action = "inventory.adjust"

        after_row = conn.execute(
            text("SELECT * FROM inventory WHERE id = :inventory_id"),
            {"inventory_id": inventory_id},
        ).mappings().first()
        after = _row_dict(after_row) or {}
        before_quantity = int(before["quantity"]) if before else 0
        delta = new_quantity - before_quantity
        if before is not None or new_quantity != 0:
            conn.execute(
                text(
                    "INSERT INTO inventory_adjustments "
                    "(inventory_id, store_id, product_id, before_quantity, after_quantity, "
                    "delta, reason, operator) "
                    "VALUES (:inventory_id, :store_id, :product_id, :before_quantity, "
                    ":after_quantity, :delta, :reason, :operator)"
                ),
                {
                    "inventory_id": inventory_id,
                    "store_id": normalized_store_id,
                    "product_id": normalized_product_id,
                    "before_quantity": before_quantity,
                    "after_quantity": new_quantity,
                    "delta": delta,
                    "reason": adjustment_reason,
                    "operator": actor,
                },
            )
        _write_audit(conn, actor, action, "inventory", inventory_id, before, after)
    return after


def clear_inventory(engine: Any, operator: str, inventory_id: int, reason: str) -> dict[str, Any]:
    actor = _clean_operator(operator)
    normalized_inventory_id = _integer(inventory_id, "库存 ID", 1)
    with engine.begin() as conn:
        row = _get_entity(conn, "inventory", normalized_inventory_id, lock=True)
    return upsert_inventory(
        engine,
        actor,
        int(row["store_id"]),
        int(row["product_id"]),
        0,
        int(row["safety_stock"]),
        reason,
    )
