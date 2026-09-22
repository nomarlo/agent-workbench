"""A stand-in for a task-queue library: `@actor` functions run on a worker, `.send` enqueues."""


def actor(function):
    function.send = function
    return function
