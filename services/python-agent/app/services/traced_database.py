from databases import Database
from contextlib import aclosing
from opentelemetry.trace import SpanKind
from app.services.tracing import traced


class TracedDatabase(Database):
    def _operation(self, name):
        # Deliberately record the operation, not query text, parameters or results.
        return traced(f"mysql.{name}", kind=SpanKind.CLIENT,
                      attributes={"db.system.name": "mysql", "db.operation.name": name})

    async def fetch_all(self, query, values=None):
        with self._operation("fetch_all"):
            return await super().fetch_all(query, values)

    async def fetch_one(self, query, values=None):
        with self._operation("fetch_one"):
            return await super().fetch_one(query, values)

    async def fetch_val(self, query, values=None, column=0):
        with self._operation("fetch_val"):
            return await super().fetch_val(query, values, column)

    async def execute(self, query, values=None):
        with self._operation("execute"):
            return await super().execute(query, values)

    async def execute_many(self, query, values):
        with self._operation("execute_many"):
            return await super().execute_many(query, values)

    async def iterate(self, query, values=None):
        with self._operation("iterate"):
            async with aclosing(super().iterate(query, values)) as rows:
                async for row in rows:
                    yield row
