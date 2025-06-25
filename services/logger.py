class LoggerService:
    def __init__(self, log_file='app.log'):
        self.log_file = log_file

    def info(self, message: str):
        print(f"ℹ️ {message}\n")

    def warning(self, message: str):
        print(f"⚠️ {message}\n")

    def error(self, message: str):
        print(f"❌ {message}\n")

    def debug(self, message: str):
        print(f"🐛 {message}\n")

    def success(self, message: str):
        print(f"✅ {message}\n")


logger_service = LoggerService()
def get_logger_service() -> LoggerService:
    """
    Dependency to get the logger service instance.
    This can be used in route handlers or other services that require logging.
    
    Returns:
        LoggerService: Instance of the logger service
    """
    return logger_service