import datetime


class DataStore:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DataStore, cls).__new__(cls)
            cls._instance.data = []
            cls._instance.forecast = {}
        return cls._instance

    # Helpers for simple in-memory storage
    def set_data(self, data):
        self.data = data
    def get_data(self):
        return self.data
    def set_forecast(self, forecast):
        self.forecast = forecast
    def get_forecast(self):
        return self.forecast
