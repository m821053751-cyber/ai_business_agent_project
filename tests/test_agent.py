from unittest.mock import MagicMock, patch
from openai import AuthenticationError, RateLimitError, APITimeoutError
import agent


def test_missing_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    answer, traces = agent.run_agent("测试查询", engine=None)
    assert "未检测到 `OPENAI_API_KEY`" in answer
    assert traces == []


def test_direct_answer_without_tools(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    with patch("agent.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_msg = MagicMock()
        mock_msg.tool_calls = None
        mock_msg.content = "本周总营业额为 12,000 元。"

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=mock_msg)]
        mock_client.chat.completions.create.return_value = mock_resp

        answer, traces = agent.run_agent("销售额是多少？", engine=None)
        assert answer == "本周总营业额为 12,000 元。"
        assert traces == []


def test_tool_calling_execution(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    with patch("agent.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        # Round 1: Model calls tool 'sales_summary'
        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_123"
        mock_tool_call.function.name = "sales_summary"
        mock_tool_call.function.arguments = '{"days": 7}'

        msg_round1 = MagicMock()
        msg_round1.tool_calls = [mock_tool_call]
        resp_round1 = MagicMock(choices=[MagicMock(message=msg_round1)])

        # Round 2: Model gives final answer
        msg_round2 = MagicMock()
        msg_round2.tool_calls = None
        msg_round2.content = "最近 7 天销售总额为 50,000 元。"
        resp_round2 = MagicMock(choices=[MagicMock(message=msg_round2)])

        mock_client.chat.completions.create.side_effect = [resp_round1, resp_round2]

        with patch.dict(agent.TOOL_REGISTRY, {"sales_summary": MagicMock(return_value={"total_revenue": 50000})}):
            answer, traces = agent.run_agent("最近7天业绩如何？", engine="fake_engine")
            assert "50,000" in answer
            assert len(traces) == 1
            assert traces[0]["tool"] == "sales_summary"
            assert traces[0]["result"] == {"total_revenue": 50000}


def test_tool_not_in_whitelist(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    with patch("agent.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_fake"
        mock_tool_call.function.name = "execute_raw_sql"
        mock_tool_call.function.arguments = '{"query": "DROP TABLE users;"}'

        msg_round1 = MagicMock(tool_calls=[mock_tool_call])
        msg_round2 = MagicMock(tool_calls=None, content="该操作未授权。")

        mock_client.chat.completions.create.side_effect = [
            MagicMock(choices=[MagicMock(message=msg_round1)]),
            MagicMock(choices=[MagicMock(message=msg_round2)]),
        ]

        answer, traces = agent.run_agent("执行删除", engine=None)
        assert len(traces) == 1
        assert "不在安全白名单中" in traces[0]["result"]["error"]


def test_max_iterations_cutoff(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    with patch("agent.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        # Infinite loop simulation
        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_loop"
        mock_tool_call.function.name = "sales_summary"
        mock_tool_call.function.arguments = '{"days": 1}'

        msg_loop = MagicMock(tool_calls=[mock_tool_call])
        resp_loop = MagicMock(choices=[MagicMock(message=msg_loop)])

        msg_final = MagicMock(tool_calls=None, content="已截断总结。")
        resp_final = MagicMock(choices=[MagicMock(message=msg_final)])

        mock_client.chat.completions.create.side_effect = [
            resp_loop, resp_loop, resp_loop, resp_loop, resp_loop, resp_final
        ]

        with patch.dict(agent.TOOL_REGISTRY, {"sales_summary": MagicMock(return_value={})}):
            answer, traces = agent.run_agent("死循环测试", engine="fake_engine")
            assert len(traces) == 5
            assert answer == "已截断总结。"


def test_api_auth_error_handling(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "invalid-key")
    with patch("agent.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_client.chat.completions.create.side_effect = AuthenticationError(
            "Invalid key", response=MagicMock(status_code=401), body={}
        )

        answer, traces = agent.run_agent("测试鉴权", engine=None)
        assert "API 鉴权失败" in answer
        assert traces == []
