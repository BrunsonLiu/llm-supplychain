class I18n:
    _current_lang = "zh"
    _translations = {
        "zh": {
            "api_title": "供应链AI智能体API",
            "api_desc": "端到端供应链决策支持系统，包含需求预测、库存优化和AI报告生成",
            "api_running": "供应链AI智能体API正在运行",
            "horizon_desc": "预测周期（周）",
            "prompt_desc": "任务提示",
            "generate_data_desc": "是否自动生成演示数据",
            "action_desc": "操作类型: generate/import/stats",
            "weeks_desc": "生成数据周期",
            "csv_path_desc": "CSV文件路径",
            "data_generate": "生成数据",
            "data_import": "导入数据",
            "forecast_prompt": "预测周期={}",
            "inventory_prompt": "库存周期={}",
            "report_prompt": "报告",
            "status_success": "success",
            "status_error": "error",
            "demo_title": "供应链AI智能体 - Portfolio演示",
            "demo_complete": "演示完成！",
            "demo_check": "[✓] 演示成功完成",
            "step_data": "步骤1: 生成演示数据...",
            "step_forecast": "步骤2: 需求预测（{}期）...",
            "step_inventory": "步骤3: 库存优化（{}期）...",
            "step_report": "步骤4: 生成供应链报告...",
            "step_summary": "步骤5: AI摘要生成...",
            "step_stats": "数据库统计:",
            "report_title": "AI驱动的供应链决策报告",
            "report_time": "生成时间: {}",
            "report_overview": "数据概况:",
            "report_products": "产品数量: {}",
            "report_records": "历史记录: {} 条",
            "report_forecasts": "预测记录: {} 条",
            "report_forecast_per": "各产品预测:",
            "report_item": "  - {}: 最新={:.1f}, 期末={:.1f}, 增长率={:.1f}%",
            "ai_summary_title": "【AI供应链决策摘要】",
            "ai_forecast_products": "• 预测产品: {}个",
            "ai_inventory_opt": "• 库存优化: {}个产品",
            "ai_report_gen": "• 报告已生成",
            "ai_suggestion": "• 建议: 关注增长趋势，优化库存周转",
            "llm_system_prompt": "你是一个专业的供应链分析师，擅长分析预测数据和库存优化结果，并提供简洁的执行摘要。",
            "llm_user_prompt": (
                "请根据以下供应链数据生成简洁的执行摘要（200字以内）：\n\n"
                "【预测概览】\n{}\n\n"
                "【订单建议】\n{}\n\n"
                "【报告】\n{}\n\n"
                "请包括：\n"
                "1. 整体需求趋势\n"
                "2. 关键产品表现\n"
                "3. 库存优化建议\n"
                "4. 风险提示"
            ),
        },
        "en": {
            "api_title": "Supply Chain AI Agent API",
            "api_desc": "End-to-end supply chain decision support system with demand forecasting, inventory optimization, and AI report generation",
            "api_running": "Supply Chain AI Agent API is running",
            "horizon_desc": "Forecast horizon (weeks)",
            "prompt_desc": "Task prompt",
            "generate_data_desc": "Auto-generate demo data",
            "action_desc": "Action type: generate/import/stats",
            "weeks_desc": "Data generation period",
            "csv_path_desc": "CSV file path",
            "data_generate": "generate data",
            "data_import": "import data",
            "forecast_prompt": "forecast horizon={}",
            "inventory_prompt": "inventory horizon={}",
            "report_prompt": "report",
            "status_success": "success",
            "status_error": "error",
            "demo_title": "Supply Chain AI Agent - Portfolio Demo",
            "demo_complete": "Demo Complete!",
            "demo_check": "[✓] Demo completed successfully",
            "step_data": "Step 1: Generate demo data...",
            "step_forecast": "Step 2: Demand Forecast ({} periods)...",
            "step_inventory": "Step 3: Inventory Optimization ({} periods)...",
            "step_report": "Step 4: Generate Supply Chain Report...",
            "step_summary": "Step 5: AI Summary Generation...",
            "step_stats": "Database Statistics:",
            "report_title": "AI-Driven Supply Chain Decision Report",
            "report_time": "Generated at: {}",
            "report_overview": "Data Overview:",
            "report_products": "Products: {}",
            "report_records": "Historical Records: {} entries",
            "report_forecasts": "Forecast Records: {} entries",
            "report_forecast_per": "Forecast per Product:",
            "report_item": "  - {}: Latest={:.1f}, End={:.1f}, Growth={:.1f}%",
            "ai_summary_title": "[AI Supply Chain Decision Summary]",
            "ai_forecast_products": "• Forecast Products: {}",
            "ai_inventory_opt": "• Inventory Optimized: {} products",
            "ai_report_gen": "• Report Generated",
            "ai_suggestion": "• Suggestion: Monitor growth trends, optimize inventory turnover",
            "llm_system_prompt": "You are a professional supply chain analyst, skilled at analyzing forecast data and inventory optimization results, and providing concise executive summaries.",
            "llm_user_prompt": (
                "Please generate a concise executive summary (within 200 words) based on the following supply chain data:\n\n"
                "[Forecast Overview]\n{}\n\n"
                "[Order Suggestions]\n{}\n\n"
                "[Report]\n{}\n\n"
                "Please include:\n"
                "1. Overall demand trend\n"
                "2. Key product performance\n"
                "3. Inventory optimization suggestions\n"
                "4. Risk alerts"
            ),
        }
    }

    @classmethod
    def set_language(cls, lang: str):
        if lang in cls._translations:
            cls._current_lang = lang

    @classmethod
    def get_language(cls) -> str:
        return cls._current_lang

    @classmethod
    def t(cls, key: str, *args, **kwargs) -> str:
        lang = cls._current_lang
        text = cls._translations.get(lang, cls._translations["en"]).get(key, key)
        if args or kwargs:
            try:
                return text.format(*args, **kwargs)
            except Exception:
                return text
        return text

    @classmethod
    def get_available_languages(cls) -> list:
        return list(cls._translations.keys())
