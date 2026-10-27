from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

import management_service as management


@pytest.fixture()
def engine():
    database = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with database.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE stores ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, name VARCHAR(100) NOT NULL, "
                "city VARCHAR(50) NOT NULL, manager VARCHAR(50), "
                "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE products ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, sku VARCHAR(50) UNIQUE NOT NULL, "
                "name VARCHAR(100) NOT NULL, category VARCHAR(50) NOT NULL, "
                "price DECIMAL(10, 2) NOT NULL, cost DECIMAL(10, 2) NOT NULL, "
                "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE inventory ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, store_id INTEGER NOT NULL, "
                "product_id INTEGER NOT NULL, quantity INTEGER NOT NULL DEFAULT 0, "
                "safety_stock INTEGER NOT NULL DEFAULT 10, "
                "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
                "UNIQUE (store_id, product_id))"
            )
        )
        conn.execute(
            text(
                "INSERT INTO stores (name, city, manager) "
                "VALUES ('华东旗舰店', '上海', '张经理')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO products (sku, name, category, price, cost) "
                "VALUES ('SKU001', '精品挂耳咖啡', '饮品', 68, 32)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO inventory (store_id, product_id, quantity, safety_stock) "
                "VALUES (1, 1, 12, 10)"
            )
        )
    management.ensure_management_schema(database)
    management.ensure_management_schema(database)
    return database


def test_schema_upgrade_backfills_managers_and_status(engine):
    store = management.list_stores(engine)[0]
    manager = management.list_managers(engine)[0]

    assert store["status"] == management.ACTIVE
    assert store["manager_id"] == manager["id"]
    assert store["manager_name"] == "张经理"
    assert manager["status"] == management.ACTIVE


def test_crud_inventory_adjustment_and_audit_are_transactional(engine):
    manager = management.create_manager(engine, "管理员", "赵经理", "13800000000")
    store = management.create_store(engine, "管理员", "西南体验店", "成都", manager["id"])
    product = management.create_product(
        engine,
        "管理员",
        "SKU100",
        "测试商品",
        "测试",
        Decimal("19.90"),
        Decimal("8.50"),
    )

    inventory = management.upsert_inventory(
        engine,
        "管理员",
        store["id"],
        product["id"],
        5,
        3,
        "期初入库",
    )
    assert inventory["quantity"] == 5

    adjusted = management.upsert_inventory(
        engine,
        "管理员",
        store["id"],
        product["id"],
        9,
        3,
        "补货入库",
    )
    assert adjusted["quantity"] == 9

    adjustments = management.list_inventory_adjustments(engine)
    assert adjustments[0]["before_quantity"] == 5
    assert adjustments[0]["after_quantity"] == 9
    assert adjustments[0]["delta"] == 4
    assert adjustments[0]["operator"] == "管理员"

    cleared = management.clear_inventory(engine, "管理员", inventory["id"], "报损清零")
    assert cleared["quantity"] == 0
    assert any(log["action"] == "inventory.adjust" for log in management.list_audit_logs(engine))


def test_duplicate_and_deactivation_rules(engine):
    product = management.list_products(engine)[0]
    store = management.list_stores(engine)[0]

    with pytest.raises(management.ConflictError):
        management.create_product(
            engine,
            "管理员",
            "SKU001",
            "重复 SKU",
            "测试",
            10,
            5,
        )

    with pytest.raises(management.ConflictError):
        management.set_product_status(engine, "管理员", product["id"], False)

    with pytest.raises(management.ConflictError):
        management.set_store_status(engine, "管理员", store["id"], False)

    manager = management.list_managers(engine)[0]
    with pytest.raises(management.ConflictError):
        management.set_manager_status(engine, "管理员", manager["id"], False)


def test_invalid_inventory_and_manager_validation(engine):
    store = management.list_stores(engine)[0]
    product = management.list_products(engine)[0]

    with pytest.raises(management.ValidationError):
        management.upsert_inventory(
            engine,
            "管理员",
            store["id"],
            product["id"],
            -1,
            10,
            "非法库存",
        )

    with pytest.raises(management.ValidationError):
        management.upsert_inventory(
            engine,
            "管理员",
            store["id"],
            product["id"],
            1,
            10,
            "",
        )

    with pytest.raises(management.ConflictError):
        management.create_manager(engine, "管理员", "张经理")
