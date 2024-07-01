from contextlib import asynccontextmanager, AbstractAsyncContextManager
from typing import List


@asynccontextmanager
async def manage_contexts(managers: List[AbstractAsyncContextManager]):
    contexts = []
    try:
        for manager in managers:
            context = await manager.__aenter__()
            contexts.append((manager, context))
        yield [context for _manager, context in contexts]
    finally:
        for manager, context in reversed(contexts):
            await manager.__aexit__(None, None, None)
