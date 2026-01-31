def test_agent_echo_basic():
    from llm_agent.agent import Agent
    from llm_agent.tools import EchoTool

    a = Agent()
    a.register_tool(EchoTool())
    prompt = "say hello; greet world"
    results = a.run(prompt, steps=2)
    assert len(results) == 2
    assert results[0][1] == results[0][0]  # Echo returns the input
