"""Stand-ins for standard-library calls that the oldest supported Python does not have."""
import ast
import asyncio
import contextvars
import functools

try:
    from asyncio import to_thread
except ImportError:  # Python < 3.9
    async def to_thread(func, *args, **kwargs):
        """
        Run a blocking call in a worker thread and wait for its result, as asyncio.to_thread does.
        :param func: the blocking callable
        :param args: its positional arguments
        :param kwargs: its keyword arguments
        """
        loop = asyncio.get_running_loop()
        # the thread sees the caller's context variables, as it does with asyncio.to_thread
        context = contextvars.copy_context()
        return await loop.run_in_executor(None, functools.partial(context.run, func, *args, **kwargs))


def unparse(node, source=None):
    """
    The Python source of an AST node, as ast.unparse writes it. Before Python 3.9 there is no
    ast.unparse, so it is the text the node was parsed from (same code, though its quotes and
    spacing are the author's), or astor's rendering when that text is not known.
    :param node: the AST node
    :param source: the source the node was parsed from
    """
    if hasattr(ast, "unparse"):
        return ast.unparse(node)
    segment = None
    if source is not None and hasattr(ast, "get_source_segment"):  # Python 3.8
        segment = ast.get_source_segment(source, node)
    if segment is None:
        import astor
        segment = astor.to_source(node).strip()
    return segment
