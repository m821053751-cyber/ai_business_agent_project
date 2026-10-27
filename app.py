"""AI 智能经营分析与库存预警助手 - Streamlit SaaS 风格 UI (已适配当前 MySQL 表结构与 Cloud LLM API)"""
from __future__ import annotations

import hmac
import html
import os
from datetime import date, timedelta
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import text

from db import check_db, get_engine
import management_service as management
from tools import low_stock, period_sales_detail, sales_summary, store_comparison, top_products

# 兼容导入 run_agent 或 answer_question
try:
    from agent import run_agent
except ImportError:
    run_agent = None

try:
    from agent import answer_question as _orig_answer_question
except ImportError:
    _orig_answer_question = None

load_dotenv()


def answer_question(engine: Any, question: str, chat_history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """兼容包装器：自动对接项目中的 run_agent / answer_question 并支持历史上下文"""
    if _orig_answer_question is not None:
        try:
            return _orig_answer_question(engine, question, chat_history=chat_history)
        except TypeError:
            return _orig_answer_question(engine, question)
    if run_agent is not None:
        try:
            res = run_agent(question, engine, chat_history=chat_history)
        except TypeError:
            res = run_agent(question, engine)
        if isinstance(res, tuple) and len(res) == 2:
            ans, trace = res
            return {"answer": ans, "trace": trace}
        if isinstance(res, dict):
            return res
        return {"answer": str(res), "trace": []}
    raise RuntimeError("未找到可用的 Agent 问答函数 (run_agent)")


st.set_page_config(
    page_title="青禾 · AI 经营分析工作台",
    page_icon=":material/monitoring:",
    layout="wide",
    initial_sidebar_state="expanded",
)

# -----------------------------------------------------------------------------
# Design system
# -----------------------------------------------------------------------------
CUSTOM_CSS = r"""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Noto+Sans+SC:wght@400;500;600;700;800&display=swap');
:root { --ink:#172033; --muted:#758198; --line:#e8edf5; --primary:#5b67e8; --primary-soft:#eef0ff; --mint:#20b486; --amber:#e9a23b; --rose:#e26375; }
html, body, [class*="css"] { font-family:'DM Sans','Noto Sans SC',sans-serif; }
.stApp { background:#f5f7fb; color:var(--ink); }
header[data-testid="stHeader"] { background:rgba(245,247,251,.85); }
.block-container { max-width:1500px; padding-top:1.6rem; padding-bottom:3rem; }
[data-testid="stSidebar"] { background:#111827; border-right:1px solid #202a3b; }
[data-testid="stSidebar"] > div:first-child { background:#111827; }
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] span { color:#c2cada; }
[data-testid="stSidebar"] hr { border-color:#293347; margin:1.25rem 0; }
[data-testid="stSidebar"] [data-testid="stRadio"] label { border-radius:8px; padding:9px 11px; margin:2px 0; transition:background .15s ease; }
[data-testid="stSidebar"] [data-testid="stRadio"] label:hover { background:#1d293b; }
[data-testid="stSidebar"] [data-testid="stRadio"] label p { font-weight:500; font-size:14px; }
[data-testid="stSidebar"] [data-testid="stRadio"] div[role="radio"] { display:none; }
.brand-wrap { padding:8px 4px 18px; }
.brand-icon { display:inline-flex; width:42px; height:42px; border-radius:8px; align-items:center; justify-content:center; color:#fff; font-size:11px; font-weight:800; letter-spacing:.4px; background:#5b67e8; box-shadow:0 9px 22px rgba(60,72,176,.26); vertical-align:middle; }
.brand-name { display:inline-block; margin-left:10px; vertical-align:middle; color:white; font-weight:750; font-size:16px; letter-spacing:.2px; }
.brand-sub { margin:8px 0 0 2px; font-size:11px; color:#7e8ba4; letter-spacing:1.6px; text-transform:uppercase; }
.side-label { font-size:10px; font-weight:700; color:#64738c; letter-spacing:1.8px; text-transform:uppercase; margin:8px 0 9px 3px; }
.side-status { border:1px solid #29364a; background:#172235; padding:12px; border-radius:8px; margin:6px 0 3px; }
.side-status-row { display:flex; align-items:center; gap:8px; color:#d9e2f0; font-size:12px; margin:5px 0; }
.dot { width:7px; height:7px; border-radius:50%; display:inline-block; background:#25c58a; box-shadow:0 0 0 4px rgba(37,197,138,.12); }
.dot.warn { background:#e9a23b; box-shadow:0 0 0 4px rgba(233,162,59,.12); }
.sidebar-foot { color:#8c99ae; font-size:10px; line-height:1.7; padding:8px 3px 0; }
.page-top { display:flex; justify-content:space-between; align-items:flex-start; gap:18px; margin-bottom:22px; }
.page-title { color:#172033; font-size:28px; line-height:1.25; font-weight:800; letter-spacing:0; margin:0; }
.page-desc { color:#667287; font-size:13px; margin-top:8px; }
.pill { display:inline-flex; align-items:center; gap:7px; border-radius:999px; padding:8px 12px; white-space:nowrap; font-size:11px; font-weight:700; border:1px solid #dfe6f0; color:#66738a; background:white; }
.pill-live { color:#087d58; border-color:#c9f0df; background:#effcf6; }
.pill-demo { color:#9b6712; border-color:#f5e4be; background:#fff9eb; }
.pill-dot { height:6px; width:6px; border-radius:50%; display:inline-block; background:currentColor; }
.section-head { display:flex; justify-content:space-between; align-items:center; gap:10px; margin:4px 0 13px; }
.section-title { color:#202a3c; font-size:15px; font-weight:750; margin:0; }
.section-hint { color:#647084; font-size:11px; }
.metric-card { height:100%; background:#fff; border:1px solid #e7ecf4; border-radius:8px; padding:18px 19px 17px; }
.metric-top { display:flex; align-items:center; justify-content:space-between; color:#7b879b; font-size:12px; font-weight:600; }
.metric-val { color:#172033; font-size:25px; letter-spacing:0; line-height:1.3; font-weight:800; margin:12px 0 6px; }
.metric-foot { font-size:11px; color:#647084; }
.metric-foot b { color:#1ca679; font-weight:700; }
.surface { background:#fff; border:1px solid #e7ecf4; border-radius:8px; padding:18px 20px; }
.insight-box { background:#f5f6ff; border:1px solid #e1e5ff; border-radius:8px; padding:15px 16px; }
.insight-title { font-size:14px; color:#252f48; font-weight:750; margin-top:6px; }
.insight-text { font-size:12px; color:#6e7890; line-height:1.7; margin-top:5px; }
.alert-row { display:flex; align-items:flex-start; gap:11px; padding:12px 0; border-bottom:1px solid #edf0f6; }
.alert-row:last-child { border-bottom:0; padding-bottom:2px; }
.alert-icon { display:flex; align-items:center; justify-content:center; flex-shrink:0; height:34px; width:34px; border-radius:8px; background:#fff2f3; color:#d9485f; font-size:15px; }
.alert-name { font-size:12px; font-weight:700; color:#273247; }
.alert-meta { font-size:11px; color:#647084; margin-top:4px; }
.alert-chip { margin-left:auto; white-space:nowrap; padding:4px 7px; background:#fff1f2; color:#d9485f; border-radius:7px; font-size:10px; font-weight:750; }
.rank-pill { display:inline-flex; align-items:center; justify-content:center; width:22px; height:22px; border-radius:7px; background:#f0f2ff; color:#5b67e8; font-size:11px; font-weight:800; }
.tip-card { border:1px solid #e6ebf3; background:white; border-radius:8px; padding:13px 14px; }
.tip-title { color:#283349; font-size:12px; font-weight:750; margin-bottom:5px; }
.tip-body { color:#647084; font-size:11px; line-height:1.6; }
.chat-bubble { background:#fff; border:1px solid #e5eaf2; border-radius:8px; padding:14px 16px; color:#344057; font-size:13px; line-height:1.8; }
.st-key-agent_composer { padding:8px 0 14px; margin:0 0 4px; background:#f5f7fb; }
.st-key-agent_composer [data-testid="stForm"] { background:#fff; border:1px solid transparent; border-radius:8px; padding:14px 14px 10px; box-shadow:0 10px 30px rgba(25,42,70,.08); transition:border-color .18s ease,box-shadow .18s ease; }
.st-key-agent_composer [data-testid="stForm"]:focus-within { border-color:#bfc6fa; box-shadow:0 10px 30px rgba(25,42,70,.1),0 0 0 3px rgba(91,103,232,.08); }
.st-key-agent_composer textarea { font-size:14px; line-height:1.65; }
.st-key-agent_composer [data-testid="stButton"] button,
.st-key-agent_composer [data-testid="stFormSubmitButton"] button { min-height:44px; }
.agent-log-head { display:flex; align-items:center; justify-content:space-between; margin:16px 0 12px; }
.agent-log-title { color:#4d5a70; font-size:11px; font-weight:750; letter-spacing:1.2px; text-transform:uppercase; }
.small-muted { color:#647084; font-size:11px; }
div[data-testid="stMetric"] { background:#fff; border:1px solid #e7ecf4; border-radius:8px; padding:15px 17px; }
div[data-testid="stMetricLabel"] { color:#78849a; font-size:12px; }
div[data-testid="stMetricValue"] { color:#172033; font-weight:800; }
.stButton > button { border-radius:8px; font-weight:650; min-height:40px; border-color:#e2e7f0; }
.stButton > button[kind="primary"] { background:#5b67e8; border-color:#5b67e8; color:#fff; box-shadow:0 5px 12px rgba(91,103,232,.15); }
.stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] > div { border-radius:8px; }
.stButton > button:focus-visible, .stTextInput input:focus-visible, .stTextArea textarea:focus-visible,
.stSelectbox div[data-baseweb="select"]:focus-within { outline:2px solid #7c86f4; outline-offset:2px; }
.stTextInput input, .stTextArea textarea { caret-color:#5b67e8; }
::selection { background:#dfe3ff; color:#172033; }
.material-symbols-rounded { font-size:18px; line-height:1; }
div[data-testid="stDataFrame"] { border:1px solid #e7ecf4; border-radius:8px; overflow:hidden; background:#fff; }
div[data-testid="stPlotlyChart"] { background:#fff; border:1px solid #e7ecf4; border-radius:8px; padding:8px 8px 2px; }
[data-testid="stChatMessage"] { background:#fff; border:1px solid #e7ecf4; border-radius:8px; padding:10px 13px; }
.admin-session { display:flex; align-items:center; justify-content:space-between; gap:12px; border:1px solid #dce6df; background:#f4fbf7; border-radius:8px; padding:10px 12px; margin:4px 0 14px; }
.admin-session b { color:#176c4f; font-size:12px; }
.admin-session span { color:#668074; font-size:11px; }
[data-testid="stTabs"] [data-baseweb="tab-list"] { gap:4px; border-bottom:1px solid #e2e8f2; }
[data-testid="stTabs"] button[data-baseweb="tab"] { font-weight:650; padding-left:13px; padding-right:13px; }
.stCaption, [data-testid="stCaptionContainer"] { color:#8792a5; }
hr { border-color:#e7ecf4; }
@media (max-width: 1100px) {
  div[data-testid="stHorizontalBlock"]:has(> div[data-testid="stColumn"] .st-key-agent_composer) { flex-direction:column; gap:1rem; }
  div[data-testid="stHorizontalBlock"]:has(> div[data-testid="stColumn"] .st-key-agent_composer) > div[data-testid="stColumn"] { width:100% !important; min-width:0; flex:1 1 100% !important; }
  div[data-testid="stHorizontalBlock"]:has(> div[data-testid="stColumn"] .st-key-agent_composer) > div[data-testid="stColumn"]:nth-child(2) > div[data-testid="stVerticalBlock"] { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; }
  div[data-testid="stHorizontalBlock"]:has(> div[data-testid="stColumn"] .st-key-agent_composer) > div[data-testid="stColumn"]:nth-child(2) > div[data-testid="stVerticalBlock"] > div[data-testid="stElementContainer"] { grid-column:1/-1; }
  div[data-testid="stHorizontalBlock"]:has(> div[data-testid="stColumn"] .st-key-agent_composer) > div[data-testid="stColumn"]:nth-child(2) > div[data-testid="stVerticalBlock"] > div[data-testid="stElementContainer"]:has([data-testid="stButton"]) { grid-column:auto; }
  div[data-testid="stHorizontalBlock"]:has(> div[data-testid="stColumn"] .st-key-agent_composer) > div[data-testid="stColumn"]:nth-child(2) [data-testid="stButton"] button { height:auto; min-height:44px; padding:9px 10px; white-space:normal; line-height:1.35; }
  div[data-testid="stHorizontalBlock"]:has(> div[data-testid="stColumn"] .st-key-agent_composer) > div[data-testid="stColumn"]:nth-child(2) [data-testid="stButton"] p { white-space:normal; }
}
@media (max-width: 768px) { .page-title {font-size:23px;} .page-top {display:block;} .page-top .pill {margin-top:12px;} .metric-val {font-size:22px;} .st-key-agent_composer {padding-top:6px;} }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# Database / demo data & Schema Normalization
# -----------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def make_engine():
    return get_engine()


def connect_db() -> tuple[Any | None, bool, str | None]:
    try:
        engine = make_engine()
        if check_db(engine):
            return engine, True, None
        return engine, False, "数据库连接检查没有通过。"
    except Exception as exc:
        return None, False, str(exc)


def _demo_data(days: int) -> dict[str, Any]:
    """当 MySQL 未连接时使用的内置演示数据"""
    end = date.today()
    dates = [end - timedelta(days=i) for i in range(days - 1, -1, -1)]
    trend_rows = []
    for idx, d in enumerate(dates):
        rev = float(1800 + (idx * 317) % 1200 + (idx % 4) * 180)
        gp = round(rev * (0.48 + (idx % 5) * 0.015), 2)
        orders = int(6 + (idx * 3) % 8)
        trend_rows.append({"order_date": pd.to_datetime(d), "revenue": rev, "gross_profit": gp, "order_count": orders})
    trend = pd.DataFrame(trend_rows)
    revenue = float(trend["revenue"].sum()) if not trend.empty else 0.0
    gross_profit = float(trend["gross_profit"].sum()) if not trend.empty else 0.0
    order_count = int(trend["order_count"].sum()) if not trend.empty else 0
    scale = max(days / 7, 0.2)
    stores = [
        {"store_name": "华东旗舰店", "revenue": round(revenue * .38, 2), "gross_profit": round(gross_profit * .39, 2), "order_count": int(order_count * .38)},
        {"store_name": "华南概念店", "revenue": round(revenue * .34, 2), "gross_profit": round(gross_profit * .33, 2), "order_count": int(order_count * .34)},
        {"store_name": "北方直营店", "revenue": round(revenue * .28, 2), "gross_profit": round(gross_profit * .28, 2), "order_count": int(order_count * .28)},
    ]
    products = [
        {"product_name": "精品挂耳咖啡", "units_sold": int(68 * scale), "revenue": round(4624 * scale, 2)},
        {"product_name": "双层隔热玻璃杯", "units_sold": int(52 * scale), "revenue": round(3016 * scale, 2)},
        {"product_name": "冻干黑咖啡粉", "units_sold": int(65 * scale), "revenue": round(2925 * scale, 2)},
        {"product_name": "手冲咖啡壶套装", "units_sold": int(9 * scale), "revenue": round(2691 * scale, 2)},
        {"product_name": "冷萃咖啡浓缩液", "units_sold": int(58 * scale), "revenue": round(2088 * scale, 2)},
    ]
    stock = [
        {"store_name": "华南概念店", "product_name": "冷萃咖啡浓缩液", "stock_qty": 5, "reorder_level": 15, "suggested_replenishment": 25},
        {"store_name": "北方直营店", "product_name": "电动奶泡机", "stock_qty": 6, "reorder_level": 15, "suggested_replenishment": 24},
        {"store_name": "华东旗舰店", "product_name": "海盐黄油曲奇", "stock_qty": 8, "reorder_level": 15, "suggested_replenishment": 22},
    ]
    return {
        "summary": {
            "revenue": revenue,
            "gross_profit": gross_profit,
            "order_count": order_count,
            "period_start": str(dates[0]) if dates else str(end),
            "period_end": str(end),
        },
        "trend": trend,
        "stores": stores,
        "products": products,
        "stock": stock,
    }


def _sales_trend(engine: Any, days: int) -> pd.DataFrame:
    """适配当前 5 张表结构（sales_orders + sales_order_items + products）的趋势查询"""
    end = date.today()
    start = end - timedelta(days=days - 1)
    sql = text("""
        SELECT o.order_date AS order_date,
               COALESCE(SUM(i.subtotal), 0) AS revenue,
               COALESCE(SUM(i.quantity * (i.unit_price - p.cost)), 0) AS gross_profit,
               COUNT(DISTINCT o.id) AS order_count
        FROM sales_orders o
        JOIN sales_order_items i ON i.order_id = o.id
        JOIN products p ON p.id = i.product_id
        WHERE o.order_date >= :start_date
          AND o.order_date <= :end_date
        GROUP BY o.order_date
        ORDER BY o.order_date
    """)
    with engine.connect() as conn:
        rows = conn.execute(sql, {"start_date": start, "end_date": end}).mappings().all()
    df = pd.DataFrame([dict(r) for r in rows])
    calendar = pd.DataFrame({"order_date": pd.to_datetime([start + timedelta(days=i) for i in range(days)])})
    if df.empty:
        df = calendar.copy()
        df["revenue"] = 0.0
        df["gross_profit"] = 0.0
        df["order_count"] = 0
    else:
        df["order_date"] = pd.to_datetime(df["order_date"])
        df = calendar.merge(df, on="order_date", how="left")
        for col in ["revenue", "gross_profit", "order_count"]:
            df[col] = df[col].fillna(0)
    df["revenue"] = pd.to_numeric(df["revenue"], errors="coerce").fillna(0.0)
    df["gross_profit"] = pd.to_numeric(df["gross_profit"], errors="coerce").fillna(0.0)
    df["order_count"] = pd.to_numeric(df["order_count"], errors="coerce").fillna(0).astype(int)
    return df


def fetch_data(engine: Any, days: int) -> dict[str, Any]:
    """读取 tools.py 数据并自动映射对齐 UI 所需的字段名"""
    raw_summary = sales_summary(engine, days) or {}
    summary = {
        "revenue": raw_summary.get("revenue", raw_summary.get("total_revenue", 0.0)),
        "gross_profit": raw_summary.get("gross_profit", raw_summary.get("total_gross_profit", 0.0)),
        "order_count": raw_summary.get("order_count", raw_summary.get("total_orders", 0)),
    }

    raw_products = top_products(engine, days, 5) or []
    products = []
    for p in raw_products:
        products.append({
            "product_name": p.get("product_name", ""),
            "units_sold": p.get("units_sold", p.get("total_sold", p.get("quantity_sold", 0))),
            "revenue": p.get("revenue", p.get("total_revenue", 0.0)),
        })

    raw_stock = low_stock(engine) or []
    stock = []
    for s in raw_stock:
        cur = int(s.get("stock_qty", s.get("current_stock", s.get("quantity", 0))) or 0)
        lvl = int(s.get("reorder_level", s.get("safety_stock", 15)) or 15)
        sug = int(s.get("suggested_replenishment", s.get("suggested_restock_qty", max(lvl * 2 - cur, 5))) or 0)
        stock.append({
            "store_name": s.get("store_name", ""),
            "product_name": s.get("product_name", ""),
            "stock_qty": cur,
            "reorder_level": lvl,
            "suggested_replenishment": sug,
        })

    raw_stores = store_comparison(engine, days) or []
    stores = []
    for st_row in raw_stores:
        stores.append({
            "store_name": st_row.get("store_name", ""),
            "revenue": st_row.get("revenue", st_row.get("total_revenue", 0.0)),
            "gross_profit": st_row.get("gross_profit", st_row.get("total_gross_profit", 0.0)),
            "order_count": st_row.get("order_count", st_row.get("total_orders", 0)),
        })

    trend = _sales_trend(engine, days)
    return {"summary": summary, "products": products, "stock": stock, "stores": stores, "trend": trend}


def money(value: Any) -> str:
    try:
        return f"¥{float(value or 0):,.2f}"
    except (TypeError, ValueError):
        return "¥0.00"


def section_head(title: str, hint: str = "") -> None:
    safe_title = html.escape(title)
    safe_hint = html.escape(hint)
    st.markdown(
        f'<div class="section-head"><div class="section-title">{safe_title}</div><div class="section-hint">{safe_hint}</div></div>',
        unsafe_allow_html=True,
    )


def page_header(eyebrow: str, title: str, description: str, live: bool) -> None:
    status = '<span class="pill pill-live"><span class="pill-dot"></span> MySQL 实时数据</span>' if live else '<span class="pill pill-demo"><span class="pill-dot"></span> 演示数据模式</span>'
    st.markdown(
        f'<div class="page-top"><div><h1 class="page-title">{html.escape(title)}</h1>'
        f'<div class="page-desc">{html.escape(description)}</div></div><div>{status}</div></div>',
        unsafe_allow_html=True,
    )


def metric_card(label: str, value: str, foot: str) -> None:
    st.markdown(
        f'<div class="metric-card"><div class="metric-top"><span>{html.escape(label)}</span></div>'
        f'<div class="metric-val">{html.escape(value)}</div>'
        f'<div class="metric-foot">{foot}</div></div>',
        unsafe_allow_html=True,
    )


def plot_theme(fig: go.Figure, height: int = 300) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=4, r=7, t=16, b=4),
        paper_bgcolor="rgba(255,255,255,0)",
        plot_bgcolor="rgba(255,255,255,0)",
        font=dict(family="DM Sans, Noto Sans SC, sans-serif", size=11, color="#7d889b"),
        hoverlabel=dict(bgcolor="#172033", font_color="#ffffff", bordercolor="#172033"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, font=dict(size=10)),
    )
    fig.update_xaxes(showgrid=False, zeroline=False, linecolor="#edf0f6", tickfont=dict(size=10))
    fig.update_yaxes(showgrid=True, gridcolor="#edf0f6", zeroline=False, linecolor="rgba(0,0,0,0)", tickfont=dict(size=10))
    return fig


def _management_actor() -> str:
    return (os.getenv("ADMIN_NAME") or "管理员").strip() or "管理员"


def _management_flash(kind: str, message: str) -> None:
    st.session_state["management_flash"] = (kind, message)


def _show_management_flash() -> None:
    flash = st.session_state.pop("management_flash", None)
    if not flash:
        return
    kind, message = flash
    if kind == "success":
        st.success(message)
    elif kind == "warning":
        st.warning(message)
    else:
        st.info(message)


def _show_management_error(exc: Exception) -> None:
    if isinstance(exc, management.ManagementError):
        st.error(str(exc))
    else:
        st.error(f"操作未完成：{type(exc).__name__}: {exc}")


def _status_text(status: str) -> str:
    return "在用" if status == management.ACTIVE else "已停用"


def _entity_label(row: dict[str, Any], primary: str = "name") -> str:
    return f"{row.get(primary, '')} · {_status_text(str(row.get('status', '')))}"


def _render_product_management(engine: Any, actor: str) -> None:
    rows = management.list_products(engine)
    if rows:
        frame = pd.DataFrame(rows)
        frame["状态"] = frame["status"].map(_status_text)
        view = frame.rename(
            columns={
                "sku": "SKU",
                "name": "商品名称",
                "category": "分类",
                "price": "售价（元）",
                "cost": "成本（元）",
            }
        )[["SKU", "商品名称", "分类", "售价（元）", "成本（元）", "状态"]]
        st.dataframe(
            view,
            use_container_width=True,
            hide_index=True,
            column_config={
                "售价（元）": st.column_config.NumberColumn(format="¥ %.2f"),
                "成本（元）": st.column_config.NumberColumn(format="¥ %.2f"),
            },
        )
    else:
        st.info("还没有商品资料。")

    with st.expander("新增商品", expanded=False):
        with st.form("management_product_create"):
            c1, c2 = st.columns(2)
            with c1:
                sku = st.text_input("SKU", placeholder="例如 SKU011")
                name = st.text_input("商品名称")
            with c2:
                category = st.text_input("分类", placeholder="例如 饮品")
                price = st.number_input("售价（元）", min_value=0.0, step=1.0, format="%.2f")
                cost = st.number_input("成本（元）", min_value=0.0, step=1.0, format="%.2f")
            submitted = st.form_submit_button("创建商品", type="primary", use_container_width=True)
        if submitted:
            try:
                management.create_product(engine, actor, sku, name, category, price, cost)
            except Exception as exc:
                _show_management_error(exc)
            else:
                _management_flash("success", "商品已创建。")
                st.rerun()

    if not rows:
        return

    with st.expander("编辑商品与状态", expanded=False):
        product_ids = [int(row["id"]) for row in rows]
        row_map = {int(row["id"]): row for row in rows}
        selected_id = st.selectbox(
            "选择商品",
            product_ids,
            format_func=lambda item_id: _entity_label(row_map[item_id], "sku"),
            key="management_product_select",
        )
        selected = row_map[selected_id]
        with st.form("management_product_edit"):
            c1, c2 = st.columns(2)
            with c1:
                sku = st.text_input("SKU", value=str(selected["sku"]), key=f"product_sku_{selected_id}")
                name = st.text_input(
                    "商品名称", value=str(selected["name"]), key=f"product_name_{selected_id}"
                )
            with c2:
                category = st.text_input(
                    "分类", value=str(selected["category"]), key=f"product_category_{selected_id}"
                )
                price = st.number_input(
                    "售价（元）",
                    min_value=0.0,
                    value=float(selected["price"]),
                    step=1.0,
                    format="%.2f",
                    key=f"product_price_{selected_id}",
                )
                cost = st.number_input(
                    "成本（元）",
                    min_value=0.0,
                    value=float(selected["cost"]),
                    step=1.0,
                    format="%.2f",
                    key=f"product_cost_{selected_id}",
                )
            saved = st.form_submit_button("保存商品修改", type="primary", use_container_width=True)
        if saved:
            try:
                management.update_product(engine, actor, selected_id, sku, name, category, price, cost)
            except Exception as exc:
                _show_management_error(exc)
            else:
                _management_flash("success", "商品资料已更新。")
                st.rerun()

        target_active = selected["status"] == management.INACTIVE
        with st.form("management_product_status"):
            st.caption("停用前必须将各门店库存调整为 0；历史销售记录会被保留。")
            confirmed = True
            if not target_active:
                confirmed = st.checkbox("我确认停用这个商品", key=f"product_confirm_{selected_id}")
            status_saved = st.form_submit_button(
                "恢复商品" if target_active else "停用商品",
                use_container_width=True,
            )
        if status_saved:
            if not confirmed:
                st.warning("请先勾选停用确认。")
            else:
                try:
                    management.set_product_status(engine, actor, selected_id, target_active)
                except Exception as exc:
                    _show_management_error(exc)
                else:
                    _management_flash("success", "商品状态已更新。")
                    st.rerun()


def _render_manager_management(engine: Any, actor: str) -> None:
    rows = management.list_managers(engine)
    if rows:
        frame = pd.DataFrame(rows)
        frame["状态"] = frame["status"].map(_status_text)
        view = frame.rename(
            columns={
                "name": "经理姓名",
                "phone": "联系电话",
                "assigned_store_count": "负责门店数",
            }
        )[["经理姓名", "联系电话", "负责门店数", "状态"]]
        st.dataframe(view, use_container_width=True, hide_index=True)
    else:
        st.info("还没有经理资料。")

    with st.expander("新增经理", expanded=False):
        with st.form("management_manager_create"):
            name = st.text_input("经理姓名")
            phone = st.text_input("联系电话（可选）")
            submitted = st.form_submit_button("创建经理", type="primary", use_container_width=True)
        if submitted:
            try:
                management.create_manager(engine, actor, name, phone)
            except Exception as exc:
                _show_management_error(exc)
            else:
                _management_flash("success", "经理已创建。")
                st.rerun()

    if not rows:
        return

    with st.expander("编辑经理与状态", expanded=False):
        manager_ids = [int(row["id"]) for row in rows]
        row_map = {int(row["id"]): row for row in rows}
        selected_id = st.selectbox(
            "选择经理",
            manager_ids,
            format_func=lambda item_id: _entity_label(row_map[item_id]),
            key="management_manager_select",
        )
        selected = row_map[selected_id]
        with st.form("management_manager_edit"):
            name = st.text_input("经理姓名", value=str(selected["name"]), key=f"manager_name_{selected_id}")
            phone = st.text_input(
                "联系电话（可选）",
                value=str(selected.get("phone") or ""),
                key=f"manager_phone_{selected_id}",
            )
            saved = st.form_submit_button("保存经理修改", type="primary", use_container_width=True)
        if saved:
            try:
                management.update_manager(engine, actor, selected_id, name, phone)
            except Exception as exc:
                _show_management_error(exc)
            else:
                _management_flash("success", "经理资料已更新。")
                st.rerun()

        target_active = selected["status"] == management.INACTIVE
        with st.form("management_manager_status"):
            st.caption("仍有在营门店归属该经理时不能停用，请先到门店页改派负责人。")
            confirmed = True
            if not target_active:
                confirmed = st.checkbox("我确认停用这个经理", key=f"manager_confirm_{selected_id}")
            status_saved = st.form_submit_button(
                "恢复经理" if target_active else "停用经理",
                use_container_width=True,
            )
        if status_saved:
            if not confirmed:
                st.warning("请先勾选停用确认。")
            else:
                try:
                    management.set_manager_status(engine, actor, selected_id, target_active)
                except Exception as exc:
                    _show_management_error(exc)
                else:
                    _management_flash("success", "经理状态已更新。")
                    st.rerun()


def _render_store_management(engine: Any, actor: str) -> None:
    rows = management.list_stores(engine)
    manager_rows = management.list_managers(engine)
    active_managers = [row for row in manager_rows if row["status"] == management.ACTIVE]

    if rows:
        frame = pd.DataFrame(rows)
        frame["状态"] = frame["status"].map(_status_text)
        view = frame.rename(
            columns={
                "name": "门店名称",
                "city": "城市",
                "manager_name": "负责人",
                "manager_phone": "负责人电话",
            }
        )[["门店名称", "城市", "负责人", "负责人电话", "状态"]]
        view["负责人"] = view["负责人"].fillna("未设置")
        view["负责人电话"] = view["负责人电话"].fillna("—")
        st.dataframe(view, use_container_width=True, hide_index=True)
    else:
        st.info("还没有门店资料。")

    manager_options = [0] + [int(row["id"]) for row in active_managers]
    manager_map = {int(row["id"]): row for row in active_managers}

    def manager_name(manager_id: int) -> str:
        return "暂不分配" if manager_id == 0 else str(manager_map[manager_id]["name"])

    with st.expander("新增门店", expanded=False):
        if not active_managers:
            st.caption("当前没有可分配的在用经理，可先创建门店，稍后补充负责人。")
        with st.form("management_store_create"):
            c1, c2 = st.columns(2)
            with c1:
                name = st.text_input("门店名称")
                city = st.text_input("城市")
            with c2:
                manager_id = st.selectbox(
                    "负责人",
                    manager_options,
                    format_func=manager_name,
                    key="store_create_manager",
                )
            submitted = st.form_submit_button("创建门店", type="primary", use_container_width=True)
        if submitted:
            try:
                management.create_store(engine, actor, name, city, manager_id or None)
            except Exception as exc:
                _show_management_error(exc)
            else:
                _management_flash("success", "门店已创建。")
                st.rerun()

    if not rows:
        return

    with st.expander("编辑门店与状态", expanded=False):
        store_ids = [int(row["id"]) for row in rows]
        row_map = {int(row["id"]): row for row in rows}
        selected_id = st.selectbox(
            "选择门店",
            store_ids,
            format_func=lambda item_id: _entity_label(row_map[item_id]),
            key="management_store_select",
        )
        selected = row_map[selected_id]
        current_manager_id = int(selected["manager_id"]) if selected.get("manager_id") else 0
        edit_manager_options = list(manager_options)
        if current_manager_id and current_manager_id not in edit_manager_options:
            edit_manager_options.append(current_manager_id)
            manager_map[current_manager_id] = {
                "id": current_manager_id,
                "name": str(selected.get("manager_name") or "已停用经理"),
            }
        if selected.get("manager_phone") is None and current_manager_id:
            st.caption("当前负责人已停用或未维护电话，保存前建议改派到在用经理。")
        with st.form("management_store_edit"):
            c1, c2 = st.columns(2)
            with c1:
                name = st.text_input("门店名称", value=str(selected["name"]), key=f"store_name_{selected_id}")
                city = st.text_input("城市", value=str(selected["city"]), key=f"store_city_{selected_id}")
            with c2:
                manager_id = st.selectbox(
                    "负责人",
                    edit_manager_options,
                    index=(
                        edit_manager_options.index(current_manager_id)
                        if current_manager_id in edit_manager_options
                        else 0
                    ),
                    format_func=manager_name,
                    key=f"store_manager_{selected_id}",
                )
            saved = st.form_submit_button("保存门店修改", type="primary", use_container_width=True)
        if saved:
            try:
                management.update_store(engine, actor, selected_id, name, city, manager_id or None)
            except Exception as exc:
                _show_management_error(exc)
            else:
                _management_flash("success", "门店资料已更新。")
                st.rerun()

        target_active = selected["status"] == management.INACTIVE
        with st.form("management_store_status"):
            st.caption("停用前必须将门店库存调整为 0；历史订单与负责人记录会被保留。")
            confirmed = True
            if not target_active:
                confirmed = st.checkbox("我确认停用这个门店", key=f"store_confirm_{selected_id}")
            status_saved = st.form_submit_button(
                "恢复门店" if target_active else "停用门店",
                use_container_width=True,
            )
        if status_saved:
            if not confirmed:
                st.warning("请先勾选停用确认。")
            else:
                try:
                    management.set_store_status(engine, actor, selected_id, target_active)
                except Exception as exc:
                    _show_management_error(exc)
                else:
                    _management_flash("success", "门店状态已更新。")
                    st.rerun()


def _render_inventory_management(engine: Any, actor: str) -> None:
    rows = management.list_inventory(engine)
    stores = [
        row for row in management.list_stores(engine) if row["status"] == management.ACTIVE
    ]
    products = [
        row for row in management.list_products(engine) if row["status"] == management.ACTIVE
    ]

    if rows:
        frame = pd.DataFrame(rows)
        frame["门店状态"] = frame["store_status"].map(_status_text)
        frame["商品状态"] = frame["product_status"].map(_status_text)
        view = frame.rename(
            columns={
                "store_name": "门店",
                "product_name": "商品",
                "sku": "SKU",
                "quantity": "当前库存",
                "safety_stock": "补货阈值",
                "updated_at": "更新时间",
            }
        )[["门店", "商品", "SKU", "当前库存", "补货阈值", "门店状态", "商品状态", "更新时间"]]
        st.dataframe(
            view,
            use_container_width=True,
            hide_index=True,
            column_config={
                "当前库存": st.column_config.NumberColumn(format="%d"),
                "补货阈值": st.column_config.NumberColumn(format="%d"),
            },
        )
    else:
        st.info("还没有库存记录。")

    with st.expander("新增或调整库存", expanded=False):
        if not stores or not products:
            st.warning("需要至少一个在用门店和一个在用商品，才能维护库存。")
        else:
            store_map = {int(row["id"]): row for row in stores}
            product_map = {int(row["id"]): row for row in products}
            inventory_map = {
                (int(row["store_id"]), int(row["product_id"])): row for row in rows
            }
            with st.form("management_inventory_upsert"):
                c1, c2 = st.columns(2)
                with c1:
                    store_id = st.selectbox(
                        "门店",
                        list(store_map),
                        format_func=lambda item_id: str(store_map[item_id]["name"]),
                    )
                    product_id = st.selectbox(
                        "商品",
                        list(product_map),
                        format_func=lambda item_id: (
                            f'{product_map[item_id]["sku"]} · {product_map[item_id]["name"]}'
                        ),
                    )
                existing = inventory_map.get((int(store_id), int(product_id)))
                with c2:
                    quantity = st.number_input(
                        "库存数量",
                        min_value=0,
                        max_value=1_000_000,
                        value=int(existing["quantity"]) if existing else 0,
                        step=1,
                    )
                    safety_stock = st.number_input(
                        "补货阈值",
                        min_value=0,
                        max_value=1_000_000,
                        value=int(existing["safety_stock"]) if existing else 10,
                        step=1,
                    )
                reason = st.text_input("调整原因", placeholder="例如 到货入库、盘点修正、样机领用")
                submitted = st.form_submit_button(
                    "保存库存",
                    type="primary",
                    use_container_width=True,
                )
            if submitted:
                try:
                    management.upsert_inventory(
                        engine,
                        actor,
                        int(store_id),
                        int(product_id),
                        quantity,
                        safety_stock,
                        reason,
                    )
                except Exception as exc:
                    _show_management_error(exc)
                else:
                    _management_flash("success", "库存与调整流水已保存。")
                    st.rerun()

    positive_inventory = [row for row in rows if int(row["quantity"]) > 0]
    with st.expander("清空库存", expanded=False):
        if not positive_inventory:
            st.info("当前没有大于 0 的库存记录。")
        else:
            inventory_map = {int(row["id"]): row for row in positive_inventory}
            with st.form("management_inventory_clear"):
                inventory_id = st.selectbox(
                    "选择库存记录",
                    list(inventory_map),
                    format_func=lambda item_id: (
                        f'{inventory_map[item_id]["store_name"]} · '
                        f'{inventory_map[item_id]["product_name"]} · '
                        f'当前 {inventory_map[item_id]["quantity"]} 件'
                    ),
                )
                reason = st.text_input(
                    "清空原因",
                    placeholder="例如 报损清零、停售清理、盘点差异",
                    key="inventory_clear_reason",
                )
                confirmed = st.checkbox("我确认把该组合库存调整为 0")
                submitted = st.form_submit_button("确认清空库存", use_container_width=True)
            if submitted:
                if not confirmed:
                    st.warning("请先勾选清空确认。")
                else:
                    try:
                        management.clear_inventory(engine, actor, int(inventory_id), reason)
                    except Exception as exc:
                        _show_management_error(exc)
                    else:
                        _management_flash("success", "库存已清零，并记录了调整流水。")
                        st.rerun()


def _render_management_logs(engine: Any) -> None:
    adjustments = management.list_inventory_adjustments(engine)
    section_head("库存调整流水", "数量变化与原因")
    if adjustments:
        frame = pd.DataFrame(adjustments)
        view = frame.rename(
            columns={
                "store_name": "门店",
                "product_name": "商品",
                "before_quantity": "调整前",
                "after_quantity": "调整后",
                "delta": "变化",
                "reason": "原因",
                "operator": "操作人",
                "created_at": "时间",
            }
        )[["门店", "商品", "调整前", "调整后", "变化", "原因", "操作人", "时间"]]
        st.dataframe(
            view,
            use_container_width=True,
            hide_index=True,
            column_config={
                "调整前": st.column_config.NumberColumn(format="%d"),
                "调整后": st.column_config.NumberColumn(format="%d"),
                "变化": st.column_config.NumberColumn(format="%+d"),
            },
        )
    else:
        st.info("暂无库存调整流水。")

    st.write("")
    section_head("管理审计日志", "记录操作人、动作、对象和前后值")
    logs = management.list_audit_logs(engine)
    if not logs:
        st.info("暂无管理操作日志。")
        return

    action_labels = {
        "product.create": "新增商品",
        "product.update": "编辑商品",
        "product.activate": "恢复商品",
        "product.deactivate": "停用商品",
        "manager.create": "新增经理",
        "manager.update": "编辑经理",
        "manager.activate": "恢复经理",
        "manager.deactivate": "停用经理",
        "store.create": "新增门店",
        "store.update": "编辑门店",
        "store.activate": "恢复门店",
        "store.deactivate": "停用门店",
        "inventory.create": "新增库存",
        "inventory.adjust": "调整库存",
    }
    entity_labels = {
        "product": "商品",
        "manager": "经理",
        "store": "门店",
        "inventory": "库存",
    }
    frame = pd.DataFrame(logs)
    frame["动作"] = frame["action"].map(action_labels).fillna(frame["action"])
    frame["对象类型"] = frame["entity_type"].map(entity_labels).fillna(frame["entity_type"])
    view = frame.rename(
        columns={
            "operator": "操作人",
            "entity_id": "对象 ID",
            "created_at": "时间",
            "before_data": "变更前",
            "after_data": "变更后",
        }
    )[["时间", "操作人", "动作", "对象类型", "对象 ID", "变更前", "变更后"]]
    view["变更前"] = view["变更前"].map(lambda value: str(value) if value is not None else "—")
    view["变更后"] = view["变更后"].map(lambda value: str(value) if value is not None else "—")
    st.dataframe(view, use_container_width=True, hide_index=True)
    with st.expander("查看最近一次变更的前后值"):
        st.json({"before": logs[0].get("before_data"), "after": logs[0].get("after_data")})


def render_management_page(engine: Any, live_db: bool, schema_error: str | None) -> None:
    page_header(
        "MASTER DATA / 基础资料",
        "资料管理",
        "由管理员维护商品、经理、门店与库存；AI 分析助手始终保持只读。",
        live_db,
    )
    if schema_error:
        st.error("资料管理的数据结构升级没有完成，写操作已关闭。")
        with st.expander("查看升级错误"):
            st.code(schema_error[:1800])
        return
    if not live_db or engine is None:
        st.warning("资料管理需要可用的 MySQL 连接。当前不会开放任何写操作。")
        return

    expected_password = os.getenv("ADMIN_PASSWORD", "")
    if not expected_password:
        st.warning("资料管理尚未启用：请在 `.env` 中配置 `ADMIN_PASSWORD` 后重启应用。")
        st.code("ADMIN_PASSWORD=请设置一个高强度密码\nADMIN_NAME=管理员", language="bash")
        return

    if not st.session_state.get("management_authenticated"):
        st.markdown(
            '<div class="insight-box"><div class="insight-title">写操作与 AI 分析完全隔离</div>'
            '<div class="insight-text">登录后才能维护基础资料。所有修改都会经过业务校验，并记录操作人、时间、对象和变更前后值。</div></div>',
            unsafe_allow_html=True,
        )
        with st.form("management_login"):
            password = st.text_input("管理员密码", type="password")
            submitted = st.form_submit_button(
                "进入资料管理",
                type="primary",
                icon=":material/login:",
                use_container_width=True,
            )
        if submitted:
            if hmac.compare_digest(password, expected_password):
                st.session_state["management_authenticated"] = True
                _management_flash("success", "管理员身份验证通过。")
                st.rerun()
            else:
                st.error("管理员密码不正确。")
        return

    actor = _management_actor()
    info_col, action_col = st.columns([3, 1])
    with info_col:
        st.markdown(
            f'<div class="admin-session"><div><b>管理员会话已启用</b><br>'
            f'<span>当前操作人：{html.escape(actor)} · 所有写操作进入审计日志</span></div></div>',
            unsafe_allow_html=True,
        )
    with action_col:
        if st.button("退出管理", icon=":material/logout:", use_container_width=True):
            st.session_state["management_authenticated"] = False
            st.rerun()

    _show_management_flash()
    tabs = st.tabs(["商品", "经理", "门店", "库存", "操作日志"])
    with tabs[0]:
        _render_product_management(engine, actor)
    with tabs[1]:
        _render_manager_management(engine, actor)
    with tabs[2]:
        _render_store_management(engine, actor)
    with tabs[3]:
        _render_inventory_management(engine, actor)
    with tabs[4]:
        _render_management_logs(engine)


# -----------------------------------------------------------------------------
# Sidebar and data mode
# -----------------------------------------------------------------------------
engine, live_db, db_error = connect_db()

with st.sidebar:
    st.markdown(
        '<div class="brand-wrap"><span class="brand-icon">QH</span><span class="brand-name">青禾 · 智营</span>'
        '<div class="brand-sub">AI BUSINESS INTELLIGENCE</div></div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="side-label">工作台 WORKSPACE</div>', unsafe_allow_html=True)
    page = st.radio(
        "主导航",
        ["经营总览", "AI 分析助手", "销售分析", "库存预警", "门店对比", "资料管理", "工具验证"],
        label_visibility="collapsed",
    )
    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown('<div class="side-label">数据范围 DATA RANGE</div>', unsafe_allow_html=True)
    # ---- 日期范围选择（支持预设和自定义） ----
    period_option = st.selectbox(
        "统计周期或自定义日期",
        ["最近 7 天", "最近 14 天", "最近 30 天", "自定义日期"],
        index=0,
        label_visibility="collapsed",
    )
    if period_option != "自定义日期":
        # 预设区间：根据今天自动计算起止日期
        period_days = {"最近 7 天": 7, "最近 14 天": 14, "最近 30 天": 30}[period_option]
        start_date = date.today() - timedelta(days=period_days - 1)
        end_date = date.today()
    else:
        # 自定义日期范围：从数据库获取最早可查询的日期作为下限
        def get_earliest_date(engine):
            with engine.connect() as conn:
                row = conn.execute(text("SELECT MIN(order_date) AS min_date FROM sales_orders")).mappings().first()
                return row["min_date"] if row and row["min_date"] else date.today()
        min_db_date = get_earliest_date(engine) if engine else date.today()
        start_date = st.date_input("起始日期", min_value=min_db_date, max_value=date.today(), value=min_db_date)
        end_date = st.date_input("结束日期", min_value=start_date, max_value=date.today(), value=date.today())
        # 计算天数用于后续工具调用（如果需要）
        period_days = (end_date - start_date).days + 1
    # 用于后续函数调用的统一变量
    period_label = f"{start_date.isoformat()} ~ {end_date.isoformat()}"
    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown('<div class="side-label">系统连接 SYSTEM STATUS</div>', unsafe_allow_html=True)
    if live_db:
        model_name = os.getenv("MODEL_NAME") or os.getenv("OLLAMA_MODEL", "DeepSeek-V4-Flash")
        st.markdown(
            f'<div class="side-status"><div class="side-status-row"><span class="dot"></span> MySQL 数据库已连接</div>'
            f'<div class="side-status-row"><span class="dot"></span> AI 模型：{html.escape(model_name)}</div></div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="side-status"><div class="side-status-row"><span class="dot warn"></span> 演示模式已启用</div>'
            '<div class="side-status-row"><span class="dot warn"></span> 请检查 MySQL 配置</div></div>',
            unsafe_allow_html=True,
        )
        if db_error:
            with st.expander("查看连接提示"):
                st.code(db_error[:1200])
    if st.button("刷新数据", icon=":material/refresh:", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.markdown("<hr>", unsafe_allow_html=True)
    st.markdown('<div class="sidebar-foot">BUILD 1.1.0 · PERSONAL PROJECT<br>AI 只读分析 · 管理员可在资料管理维护数据</div>', unsafe_allow_html=True)

management_schema_error = None
if live_db and engine is not None:
    try:
        management.ensure_management_schema(engine)
    except Exception as exc:
        management_schema_error = f"{type(exc).__name__}: {exc}"

# Fetch current page data, falling back to clearly marked placeholders when needed.
if live_db and engine is not None:
    try:
        data = fetch_data(engine, period_days)
        live_page_data = True
    except Exception as exc:
        data = _demo_data(period_days)
        live_page_data = False
        st.warning(f"部分数据库查询未成功，当前界面使用演示数据。详情：{exc}")
else:
    data = _demo_data(period_days)
    live_page_data = False

summary = data["summary"]
trend = data["trend"].copy()
products_df = pd.DataFrame(data["products"])
stores_df = pd.DataFrame(data["stores"])
stock_df = pd.DataFrame(data["stock"])

if not products_df.empty:
    for col in ["units_sold", "revenue"]:
        if col in products_df.columns:
            products_df[col] = pd.to_numeric(products_df[col], errors="coerce").fillna(0)
if not stores_df.empty:
    for col in ["revenue", "gross_profit", "order_count"]:
        if col in stores_df.columns:
            stores_df[col] = pd.to_numeric(stores_df[col], errors="coerce").fillna(0)

# -----------------------------------------------------------------------------
# Pages
# -----------------------------------------------------------------------------
if page == "经营总览":
    page_header("OVERVIEW / 经营驾驶舱", "经营总览", "用一张看板掌握销售表现、商品动销与库存风险。", live_page_data)
    if not live_page_data:
        st.info("当前显示的是界面预览用演示数据。连接 MySQL 并确保查询成功后，会自动展示业务库数据。")

    gross_margin = (float(summary.get("gross_profit", 0) or 0) / max(float(summary.get("revenue", 0) or 0), 1)) * 100
    cols = st.columns(4, gap="medium")
    with cols[0]: metric_card("周期销售额", money(summary.get("revenue")), f"统计周期：{period_label}")
    with cols[1]: metric_card("周期毛利", money(summary.get("gross_profit")), f"毛利率约 {gross_margin:.1f}%")
    with cols[2]: metric_card("完成订单", f'{int(summary.get("order_count", 0) or 0):,}', "按周期内订单统计")
    with cols[3]: metric_card("库存预警", f"{len(stock_df):,}", "门店 / 商品组合需关注")

    st.write("")
    left, right = st.columns([1.65, 1], gap="large")
    with left:
        section_head("销售趋势", f"{period_label} · 销售额 / 毛利")
        if not trend.empty:
            trend["order_date"] = pd.to_datetime(trend["order_date"])
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=trend["order_date"], y=trend["revenue"], name="销售额", mode="lines",
                line=dict(color="#5b67e8", width=3, shape="spline"), fill="tozeroy",
                fillcolor="rgba(91,103,232,.10)", hovertemplate="%{x|%m-%d}<br>销售额 ¥%{y:,.2f}<extra></extra>"))
            fig.add_trace(go.Scatter(
                x=trend["order_date"], y=trend["gross_profit"], name="毛利", mode="lines",
                line=dict(color="#22b486", width=2.5, shape="spline", dash="dot"),
                hovertemplate="%{x|%m-%d}<br>毛利 ¥%{y:,.2f}<extra></extra>"))
            fig.update_layout(hovermode="x unified")
            fig.update_yaxes(tickprefix="¥", tickformat="~s")
            st.plotly_chart(plot_theme(fig, 315), use_container_width=True, config={"displayModeBar": False})
        else:
            st.caption("所选周期内暂无销售记录。")

    with right:
        section_head("库存风险提醒", "按补货阈值排序")
        if stock_df.empty:
            st.markdown('<div class="insight-box"><div class="insight-title">库存状态良好</div><div class="insight-text">目前没有商品低于设置的补货阈值。</div></div>', unsafe_allow_html=True)
        else:
            for _, row in stock_df.head(5).iterrows():
                store = html.escape(str(row.get("store_name", "未知门店")))
                product = html.escape(str(row.get("product_name", "未知商品")))
                qty = int(row.get("stock_qty", 0) or 0)
                level = int(row.get("reorder_level", 0) or 0)
                suggestion = int(row.get("suggested_replenishment", 0) or 0)
                st.markdown(
                    f'<div class="alert-row"><div class="alert-icon">!</div><div><div class="alert-name">{product}</div>'
                    f'<div class="alert-meta">{store} · 库存 {qty} / 阈值 {level}<br>建议补货 {suggestion} 件</div></div>'
                    f'<div class="alert-chip">低库存</div></div>', unsafe_allow_html=True)
            if len(stock_df) > 5:
                st.caption(f"还有 {len(stock_df)-5} 条库存预警，请到「库存预警」查看全部。")

    st.write("")
    c1, c2 = st.columns([1.08, 1.45], gap="large")
    with c1:
        section_head("热销商品 TOP 5", "按销量排序")
        if products_df.empty:
            st.caption("所选周期内暂无商品销售记录。")
        else:
            prod = products_df.sort_values("units_sold", ascending=True).tail(5)
            fig = px.bar(prod, x="units_sold", y="product_name", orientation="h", text="units_sold")
            fig.update_traces(marker_color="#7b83f1", marker_line_width=0, textposition="outside", cliponaxis=False,
                              hovertemplate="%{y}<br>销量 %{x:,.0f} 件<extra></extra>")
            fig.update_layout(showlegend=False, bargap=.42)
            fig.update_xaxes(title=None, showticklabels=False, showgrid=False, range=[0, max(1, float(prod["units_sold"].max()) * 1.18)])
            fig.update_yaxes(title=None, showgrid=False)
            st.plotly_chart(plot_theme(fig, 245), use_container_width=True, config={"displayModeBar": False})
    with c2:
        section_head("门店经营表现", "销售额排名")
        if stores_df.empty:
            st.caption("暂无门店数据。")
        else:
            store_chart = stores_df.sort_values("revenue", ascending=True)
            fig = px.bar(store_chart, x="revenue", y="store_name", orientation="h", text="revenue")
            fig.update_traces(marker_color="#38b991", marker_line_width=0,
                              texttemplate="¥%{x:,.0f}", textposition="outside", cliponaxis=False,
                              hovertemplate="%{y}<br>销售额 ¥%{x:,.2f}<extra></extra>")
            fig.update_layout(showlegend=False, bargap=.45)
            fig.update_xaxes(title=None, showticklabels=False, showgrid=False, range=[0, max(1, float(store_chart["revenue"].max()) * 1.22)])
            fig.update_yaxes(title=None, showgrid=False)
            st.plotly_chart(plot_theme(fig, 245), use_container_width=True, config={"displayModeBar": False})

    st.write("")
    st.markdown('<div class="insight-box"><div class="insight-title">把数据变成行动建议</div><div class="insight-text">前往「AI 分析助手」，可以用自然语言提问，例如“最近 7 天哪家门店表现最好？”或“哪些商品需要补货？”。Agent 会选择预先注册的只读工具查询业务数据，并展示工具调用证据。</div></div>', unsafe_allow_html=True)

elif page == "AI 分析助手":
    if "agent_input_version" not in st.session_state:
        st.session_state["agent_input_version"] = 0

    def set_agent_question(prompt: str) -> None:
        # Re-key the input to reset it safely after it has been instantiated.
        version = st.session_state["agent_input_version"] + 1
        st.session_state["agent_input_version"] = version
        st.session_state[f"agent_input_{version}"] = prompt

    def reset_agent_conversation() -> None:
        st.session_state["agent_history"] = []
        st.session_state["agent_input_version"] += 1

    page_header("AI COPILOT / 自然语言分析", "AI 分析助手", "像和经营分析师对话一样，用自然语言查询业务数据。", live_page_data)
    if not live_page_data:
        st.warning("当前是演示数据模式。Agent 实时查询需要先连接 MySQL。")

    period_end = date.today()
    period_start = period_end - timedelta(days=6)
    suggestions = [
        "分析最近 7 天的销售额和毛利",
        "最近 7 天销量最高的 5 种商品是什么？",
        "哪些门店商品库存不足？请给出补货建议",
        "比较最近 7 天各门店销售表现，指出表现最好的一家",
        f"查询 {period_start:%Y-%m-%d} 到 {period_end:%Y-%m-%d} 的商品销量、销售额和毛利",
        "各门店负责人分别是谁？",
    ]
    left, right = st.columns([1.65, 1], gap="large")
    with right:
        section_head("试试这样问", "QUICK PROMPTS")
        for idx, suggestion in enumerate(suggestions):
            st.button(
                suggestion,
                key=f"prompt_{idx}",
                use_container_width=True,
                on_click=set_agent_question,
                args=(suggestion,),
            )
        st.markdown("<hr>", unsafe_allow_html=True)
        st.markdown('<div class="tip-title">只读工具调用</div><div class="tip-body">模型只能够调用项目中预先注册的销售汇总、畅销商品、库存预警、门店对比、指定日期销售明细与门店负责人工具，不开放任意 SQL 执行。</div>', unsafe_allow_html=True)
    with left:
        section_head("与经营 Agent 对话", "LLM TOOL CALLING")
        if "agent_history" not in st.session_state:
            st.session_state["agent_history"] = []
        history = st.session_state["agent_history"]
        input_key = f"agent_input_{st.session_state['agent_input_version']}"
        if input_key not in st.session_state:
            st.session_state[input_key] = ""
        with st.container(key="agent_composer"):
            with st.form("agent_question_form", border=False):
                user_question = st.text_area(
                    "输入问题",
                    key=input_key,
                    height=82,
                    placeholder="例如：最近 7 天哪家门店销售额最高？",
                    label_visibility="collapsed",
                )
                send_col, clear_col = st.columns([1, 1])
                with send_col:
                    send = st.form_submit_button(
                        "开始分析",
                        type="primary",
                        icon=":material/search:",
                        use_container_width=True,
                        disabled=not live_page_data,
                    )
                with clear_col:
                    st.form_submit_button(
                        "清空对话",
                        icon=":material/restart_alt:",
                        use_container_width=True,
                        on_click=reset_agent_conversation,
                    )
        if send:
            q = (user_question or "").strip()
            if not q:
                st.warning("请先输入你想分析的问题。")
            elif not live_page_data or engine is None:
                st.error("当前没有连接到 MySQL，不能执行实时 Agent 查询。")
            else:
                recent_history = [
                    {"role": msg["role"], "content": msg["content"]}
                    for msg in history[-6:]
                    if msg.get("role") in ("user", "assistant") and msg.get("content")
                ]
                history.append({"role": "user", "content": q})
                with st.spinner("Agent 正在理解问题、选择工具并查询数据……"):
                    try:
                        result = answer_question(engine, q, chat_history=recent_history)
                        response_text = result.get("answer", "模型没有返回文本。")
                        history.append({"role": "assistant", "content": response_text, "trace": result.get("trace", [])})
                    except Exception as exc:
                        history.append({"role": "assistant", "content": f"Agent 调用失败：{type(exc).__name__}: {exc}", "trace": []})
                st.session_state["agent_history"] = history
                st.session_state["agent_input_version"] += 1
                st.rerun()
        st.markdown('<div class="agent-log-head"><span class="agent-log-title">对话记录</span><span class="section-hint">最新回复优先</span></div>', unsafe_allow_html=True)
        if not history:
            st.markdown('<div class="chat-bubble">你好，我是你的 AI 经营分析助手。你可以询问销售趋势、商品排行、门店表现或库存风险。我会先调用数据工具，再根据真实查询结果组织回答。</div>', unsafe_allow_html=True)
        for item in reversed(history[-8:]):
            with st.chat_message(item["role"]):
                st.markdown(item["content"])
                if item.get("trace"):
                    with st.expander("查看本次工具调用证据"):
                        st.json(item["trace"])

elif page == "销售分析":
    page_header("SALES ANALYTICS / 销售分析", "销售分析", "追踪销售额、毛利与商品动销，帮助识别业务变化。", live_page_data)
    if not live_page_data:
        st.info("以下为演示数据，连接 MySQL 后会自动切换为实时结果。")
    cols = st.columns(3, gap="medium")
    cols[0].metric("销售额", money(summary.get("revenue")))
    cols[1].metric("毛利", money(summary.get("gross_profit")))
    cols[2].metric("订单数", f'{int(summary.get("order_count", 0) or 0):,}')
    st.write("")
    a, b = st.columns([1.5, 1], gap="large")
    with a:
        section_head("日销售额走势", period_label)
        fig = px.line(trend, x="order_date", y="revenue", markers=True)
        fig.update_traces(line_color="#5b67e8", line_width=3, marker_size=5,
                          hovertemplate="%{x|%Y-%m-%d}<br>销售额 ¥%{y:,.2f}<extra></extra>")
        fig.update_yaxes(tickprefix="¥", tickformat="~s", title=None)
        fig.update_xaxes(title=None)
        st.plotly_chart(plot_theme(fig, 335), use_container_width=True, config={"displayModeBar": False})
    with b:
        section_head("商品销售额 TOP 5", "按销售额排序")
        if not products_df.empty:
            p = products_df.sort_values("revenue", ascending=True)
            fig = px.bar(p, x="revenue", y="product_name", orientation="h", text="revenue")
            fig.update_traces(marker_color="#5b67e8", marker_line_width=0, texttemplate="¥%{x:,.0f}", textposition="outside", cliponaxis=False)
            fig.update_xaxes(title=None, showticklabels=False, showgrid=False, range=[0, max(1, float(p["revenue"].max()) * 1.25)])
            fig.update_yaxes(title=None, showgrid=False)
            st.plotly_chart(plot_theme(fig, 335), use_container_width=True, config={"displayModeBar": False})
        else:
            st.caption("暂无商品销售记录。")
    st.write("")
    section_head("商品销售明细", "按销量排序")
    if not products_df.empty:
        products_display = products_df.sort_values("units_sold", ascending=False).copy()
        products_display.insert(0, "排名", range(1, len(products_display) + 1))
        products_display = products_display.rename(columns={"product_name": "商品名称", "units_sold": "销量（件）", "revenue": "销售额（元）"})
        st.dataframe(products_display, use_container_width=True, hide_index=True,
                     column_config={"销售额（元）": st.column_config.NumberColumn(format="¥ %.2f"), "销量（件）": st.column_config.NumberColumn(format="%d")})
    else:
        st.caption("暂无数据。")

elif page == "库存预警":
    page_header("INVENTORY HEALTH / 库存风控", "库存预警", "优先关注库存低于补货阈值的门店商品，减少缺货风险。", live_page_data)
    if not live_page_data:
        st.info("以下为演示数据，连接 MySQL 后会自动切换为实时结果。")
    alert_count = len(stock_df)
    critical_count = 0
    if not stock_df.empty and {"stock_qty", "reorder_level"}.issubset(stock_df.columns):
        critical_count = int((stock_df["stock_qty"].astype(float) <= stock_df["reorder_level"].astype(float) * .5).sum())
    c1, c2, c3 = st.columns(3, gap="medium")
    c1.metric("待关注组合", f"{alert_count}", help="门店与商品组成一个库存组合")
    c2.metric("严重缺货组合", f"{critical_count}", help="当前库存不高于补货阈值的一半")
    c3.metric("建议补货总量", f'{int(pd.to_numeric(stock_df.get("suggested_replenishment", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()):,} 件')
    st.write("")
    l, r = st.columns([1.35, 1], gap="large")
    with l:
        section_head("库存预警清单", "库存量 ≤ 补货阈值")
        if stock_df.empty:
            st.success("当前未发现低于补货阈值的商品。")
        else:
            view = stock_df.rename(columns={"store_name": "门店", "product_name": "商品", "stock_qty": "当前库存", "reorder_level": "补货阈值", "suggested_replenishment": "建议补货量"}).copy()
            st.dataframe(view, use_container_width=True, hide_index=True,
                         column_config={"当前库存": st.column_config.NumberColumn(format="%d"), "补货阈值": st.column_config.NumberColumn(format="%d"), "建议补货量": st.column_config.NumberColumn(format="%d")})
    with r:
        section_head("补货执行建议", "仅供人工判断")
        if stock_df.empty:
            st.markdown('<div class="insight-box"><div class="insight-title">暂无待处理事项</div><div class="insight-text">请继续定期查看库存变化，并确认补货阈值与实际业务规则一致。</div></div>', unsafe_allow_html=True)
        else:
            for _, row in stock_df.head(8).iterrows():
                st.markdown(f'<div class="alert-row"><div class="alert-icon">!</div><div><div class="alert-name">{html.escape(str(row.get("store_name", "")))} · {html.escape(str(row.get("product_name", "")))}</div><div class="alert-meta">当前库存 {int(row.get("stock_qty",0))} 件；建议补货 {int(row.get("suggested_replenishment",0))} 件</div></div></div>', unsafe_allow_html=True)
            st.caption("系统只生成建议，不会自动下单或修改库存。请结合在途库存、保质期和供应商交期复核。")

elif page == "门店对比":
    page_header("STORE PERFORMANCE / 门店对比", "门店经营对比", "横向对比门店销售规模、毛利贡献与订单表现。", live_page_data)
    if not live_page_data:
        st.info("以下为演示数据，连接 MySQL 后会自动切换为实时结果。")
    if not stores_df.empty:
        best_store = stores_df.sort_values("revenue", ascending=False).iloc[0]
        avg_revenue = stores_df["revenue"].mean()
        total_rev = stores_df["revenue"].sum()
        c1, c2, c3 = st.columns(3, gap="medium")
        c1.metric("门店数量", f"{len(stores_df)}")
        c2.metric("领先门店", str(best_store["store_name"]), help="按所选周期销售额排序")
        c3.metric("门店平均销售额", money(avg_revenue))
        st.write("")
        l, r = st.columns(2, gap="large")
        with l:
            section_head("销售额对比", "按销售额降序")
            fig = px.bar(stores_df.sort_values("revenue", ascending=True), x="revenue", y="store_name", orientation="h", text="revenue")
            fig.update_traces(marker_color="#5b67e8", marker_line_width=0, texttemplate="¥%{x:,.0f}", textposition="outside", cliponaxis=False)
            fig.update_xaxes(title=None, showticklabels=False, showgrid=False, range=[0, max(1, float(stores_df["revenue"].max()) * 1.25)])
            fig.update_yaxes(title=None, showgrid=False)
            st.plotly_chart(plot_theme(fig, 315), use_container_width=True, config={"displayModeBar": False})
        with r:
            section_head("毛利贡献", "各门店毛利")
            fig = px.bar(stores_df.sort_values("gross_profit", ascending=True), x="gross_profit", y="store_name", orientation="h", text="gross_profit")
            fig.update_traces(marker_color="#29b58a", marker_line_width=0, texttemplate="¥%{x:,.0f}", textposition="outside", cliponaxis=False)
            fig.update_xaxes(title=None, showticklabels=False, showgrid=False, range=[0, max(1, float(stores_df["gross_profit"].max()) * 1.25)])
            fig.update_yaxes(title=None, showgrid=False)
            st.plotly_chart(plot_theme(fig, 315), use_container_width=True, config={"displayModeBar": False})
        st.write("")
        section_head("门店指标明细", "经营指标可回溯")
        view = stores_df.copy()
        view["毛利率"] = view.apply(lambda row: (row["gross_profit"] / row["revenue"] * 100) if row["revenue"] else 0, axis=1)
        view = view.rename(columns={"store_name": "门店名称", "revenue": "销售额（元）", "gross_profit": "毛利（元）", "order_count": "订单数"})
        view = view[["门店名称", "销售额（元）", "毛利（元）", "毛利率", "订单数"]]
        st.dataframe(view, use_container_width=True, hide_index=True,
                     column_config={"销售额（元）": st.column_config.NumberColumn(format="¥ %.2f"), "毛利（元）": st.column_config.NumberColumn(format="¥ %.2f"), "毛利率": st.column_config.NumberColumn(format="%.1f%%"), "订单数": st.column_config.NumberColumn(format="%d")})
        strongest = float(best_store["revenue"])
        if total_rev:
            share = strongest / total_rev * 100
            st.markdown(f'<div class="insight-box"><div class="insight-title">{html.escape(str(best_store["store_name"]))} 当前销售额领先</div><div class="insight-text">该门店贡献了所选周期约 {share:.1f}% 的门店总销售额。建议继续核对客流、订单数、商品结构与毛利率，避免仅凭销售额判断整体经营质量。</div></div>', unsafe_allow_html=True)
    else:
        st.info("暂无门店数据。")

elif page == "资料管理":
    render_management_page(engine, live_db, management_schema_error)

elif page == "工具验证":
    page_header("TOOL VALIDATION / 工具验证", "工具验证", "用确定性工具结果核对 SQL 数据，为 Agent 输出提供证据。", live_page_data)
    st.markdown('<div class="insight-box"><div class="insight-title">AI 的回答应当可以核对，而不是“看起来合理”</div><div class="insight-text">下方直接调用 Python 工具函数，再与 AI Agent 的回答对照。只有成功执行的工具结果才能作为经营数字的依据。</div></div>', unsafe_allow_html=True)
    st.write("")
    if not live_page_data or engine is None:
        st.warning("当前处于演示数据模式，不能执行数据库工具自检。请先连接 MySQL。")
    else:
        test_funcs = [
            ("销售汇总", lambda: sales_summary(engine, period_days)),
            ("畅销商品", lambda: top_products(engine, period_days, 5)),
            ("库存预警", lambda: low_stock(engine)),
            ("门店对比", lambda: store_comparison(engine, period_days)),
            (
                "期间销售与负责人",
                lambda: period_sales_detail(
                    engine,
                    start_date=(date.today() - timedelta(days=period_days - 1)).isoformat(),
                    end_date=date.today().isoformat(),
                ),
            ),
        ]
        if st.button(
            f"运行 {len(test_funcs)} 项工具测试",
            type="primary",
            icon=":material/play_arrow:",
        ):
            results = []
            for name, func in test_funcs:
                try:
                    result = func()
                    results.append({"工具": name, "状态": "通过", "返回记录": len(result) if isinstance(result, list) else "1 个汇总对象", "详情": "查询成功"})
                    st.session_state[f"test_result_{name}"] = result
                except Exception as exc:
                    results.append({"工具": name, "状态": "失败", "返回记录": "—", "详情": f"{type(exc).__name__}: {exc}"})
                    st.session_state[f"test_result_{name}"] = None
            st.session_state["test_summary"] = results
        if "test_summary" in st.session_state:
            test_df = pd.DataFrame(st.session_state["test_summary"])
            st.dataframe(test_df, use_container_width=True, hide_index=True)
            for name, _ in test_funcs:
                with st.expander(f"查看{name}的返回数据"):
                    result = st.session_state.get(f"test_result_{name}")
                    if result is None:
                        st.error("测试失败，详情请看上方。")
                    else:
                        st.json(result)

st.markdown(
    '<div style="text-align:center;color:#a0a9b9;font-size:10px;padding:24px 0 0;letter-spacing:.5px">'
    '青禾 · AI 智能经营分析与库存预警助手 · STREAMLIT / MYSQL / LLM API · READ-ONLY ANALYTICS'
    '</div>',
    unsafe_allow_html=True,
)
