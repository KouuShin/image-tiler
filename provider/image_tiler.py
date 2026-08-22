from dify_plugin import ToolProvider


class ImageTilerProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict) -> None:
        # This offline image-processing tool has no credentials.
        return None
