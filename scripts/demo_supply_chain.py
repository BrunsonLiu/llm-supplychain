"""Demo: AI-powered demand forecast + inventory optimization for supply chain"""
from llm_agent.tools import DataTool, ForecastTool, InventoryTool, ReportTool

def run_demo():
    # Instantiate tools
    data_tool = DataTool()
    forecast_tool = ForecastTool()
    inventory_tool = InventoryTool()
    report_tool = ReportTool()

    # Load/generate data
    data_tool.run("load demo data")
    # Forecast for next horizon
    forecast = forecast_tool.run("forecast horizon=12")
    # Store forecast into DataStore via the tool
    # Inventory orders based on forecast
    orders = inventory_tool.run("inventory horizon=12")
    # Generate a basic report
    report = report_tool.run("report")

    print("Forecast:")
    print(forecast)
    print("\nOrders:")
    print(orders)
    print("\nReport:")
    print(report)

if __name__ == "__main__":
    run_demo()
