class Worker(BaseWorker, Protocol):
    def run(self, task: Task) -> Result:
        return execute(task)

    async def stop(self, *, force=False):
        return None

    def _private_helper(self):
        return "PRIVATE_METHOD_SENTINEL"
