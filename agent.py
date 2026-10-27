import os
import json
from datetime import date
from typing import Any

from openai import OpenAI, OpenAIError, AuthenticationError, RateLimitError, APITimeoutError
from tools import TOOL_DEFINITIONS, TOOL_REGISTRY

MAX_ITERATIONS = 5


def run_agent(user_query: str, engine: Any, chat_history: list[dict[str, Any]] | None = None) -> tuple[str, list[dict[str, Any]]]:
    """
    运行企业级商业经营分析 Agent。
    采用 ReAct 循环与 Tool Calling 机制，具备最大轮数保护、多轮记忆与异常降级能力。
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return (
            "⚠️ 未检测到 `OPENAI_API_KEY` 环境变量，请在 `.env` 文件中配置有效的 API 密钥后再试。",
            [],
        )

    base_url = os.getenv("OPENAI_BASE_URL", "https://api.siliconflow.cn/v1")
    model = os.getenv("MODEL_NAME", "deepseek-ai/DeepSeek-V4-Flash")
    today = date.today().isoformat()

    system_prompt = (
        "你是一名企业级智能商业经营决策助手 (AI Business Agent)。\n"
        "【核心准则】：\n"
        "1. 严禁编造任何数值！回答销售额、毛利、订单数、库存和门店表现等具体数字时，必须先调用对应数据工具。\n"
        "2. 查询明确日期范围内的商品销售明细、销售额、毛利或门店负责人时，调用 period_sales_detail。\n"
        f"3. 当前日期是 {today}。当用户提到今天、昨天、本周、本月或最近 N 天时，先按当前日期换算区间。\n"
        "4. 日期统一使用 YYYY-MM-DD，结束日期包含当天。\n"
        "5. 请依据工具返回的真实数据进行深度分析，建议包含：【核心数据洞察】、【经营问题诊断】与【落地行动对策】。"
    )

    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]

    # 载入有效历史对话上下文（支持多轮追问）
    if chat_history:
        for item in chat_history:
            if isinstance(item, dict) and item.get("role") in ("user", "assistant") and item.get("content"):
                messages.append({
                    "role": item["role"],
                    "content": str(item["content"])
                })

    messages.append({"role": "user", "content": user_query})
    tool_traces: list[dict[str, Any]] = []

    try:
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=30.0)

        iterations = 0
        while iterations < MAX_ITERATIONS:
            iterations += 1

            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
            )
            msg = response.choices[0].message
            messages.append(msg)

            # 没有工具调用，模型已产出最终分析结论
            if not msg.tool_calls:
                return msg.content or "（分析助手未返回有效内容）", tool_traces

            # 执行工具调用
            for tool_call in msg.tool_calls:
                func_name = tool_call.function.name
                try:
                    args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
                except (json.JSONDecodeError, TypeError) as parse_err:
                    args = {}
                    result = {"error": f"工具入参格式错误: {parse_err}"}
                else:
                    try:
                        if func_name in TOOL_REGISTRY:
                            func = TOOL_REGISTRY[func_name]
                            result = func(engine, **args)
                        else:
                            result = {"error": f"工具 {func_name} 不在安全白名单中"}
                    except Exception as exc:
                        result = {"error": f"{type(exc).__name__}: {exc}"}

                tool_traces.append({
                    "tool": func_name,
                    "arguments": args,
                    "result": result,
                })

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": func_name,
                    "content": json.dumps(result, default=str, ensure_ascii=False),
                })

        # 超过最大轮数截断保护，强制模型根据已收集数据做最终陈述
        messages.append({
            "role": "user",
            "content": "已达到最大工具调用次数限制，请直接根据已获取的所有数据进行总结分析与决策建议。",
        })
        fallback_resp = client.chat.completions.create(
            model=model,
            messages=messages,
        )
        final_text = fallback_resp.choices[0].message.content or "（已达最大调用轮数，分析已截断）"
        return final_text, tool_traces

    except AuthenticationError:
        return "⚠️ API 鉴权失败：请检查 `.env` 中的 `OPENAI_API_KEY` 是否有效。", tool_traces
    except RateLimitError:
        return "⚠️ 接口调用超频或账户额度不足 (Rate Limit)，请稍后再试。", tool_traces
    except APITimeoutError:
        return "⚠️ 接口调用超时，请检查网络连接或 API 服务端点可用性。", tool_traces
    except OpenAIError as oe:
        return f"⚠️ 大模型接口调用异常：{oe}", tool_traces
    except Exception as exc:
        return f"⚠️ Agent 运行发生未知异常：{type(exc).__name__}: {exc}", tool_traces


def answer_question(engine: Any, question: str, chat_history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Compatibility adapter for the Streamlit UI."""
    answer, trace = run_agent(question, engine, chat_history=chat_history)
    return {"answer": answer, "trace": trace}
