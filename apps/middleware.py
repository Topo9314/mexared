import logging

logger = logging.getLogger('apps')

class RequestLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        logger.info(f'URL Request: {request.path}')
        response = self.get_response(request)
        return response
