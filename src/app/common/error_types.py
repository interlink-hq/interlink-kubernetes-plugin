from http import HTTPStatus


class ApplicationError(Exception):
    """
    The base exception class for application errors.

    :ivar message: The descriptive message associated with the error.
    """

    template = "{message}"
    """Message template"""
    message: str
    """Rendered message template"""
    status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR.value
    """Status code associated to the error, most useful for HTTPExceptions"""

    def __init__(self, **kwargs):
        self.message = self.template.format(**kwargs)
        if "status_code" in kwargs:
            self.status_code = kwargs["status_code"]
        super().__init__(self, self.message)

    def __str__(self) -> str:
        return f"{self.message} ({self.__class__.__name__} {self.status_code})"


class ConnectionTimeout(ApplicationError):
    template = "Connection to {url} timed out"


class DataNotFoundError(ApplicationError):
    """
    The data associated with a given path could not be loaded.

    :ivar type_name: The name of the data type.
    :ivar path: The data path that the application attempted to load.
    """

    template = "Unable to find data of type {type_name} at path: {path}"
    status_code = HTTPStatus.NOT_FOUND.value


class DataSaveError(ApplicationError):
    """
    Error saving data at a given path.

    :ivar type_name: The name of the data type.
    :ivar path: The data path that the application attempted to save.
    """

    template = "Unable to save data of type {type_name} at path: {path}"


class MissingParametersError(ApplicationError):
    """
    One or more required parameters were not supplied.

    :ivar object_name: The name of the object that has missing parameters.
    :ivar missing: The names of the missing parameters.
    """

    template = "The following required parameters are missing for {object_name}: {missing}"
    status_code = HTTPStatus.BAD_REQUEST.value


class MissingPropertiesError(ApplicationError):
    """
    One or more required properties are missing.

    :ivar object_name: The name of the object that has missing properties.
    :ivar missing: The names of the missing properties.
    """

    template = "The following properties are missing for {object_name}: {missing}"


class ValidationError(ApplicationError):
    """
    An exception occurred validating parameters.

    :ivar value: The value that was being validated.
    :ivar param: The parameter that failed validation.
    :ivar type_name: The name of the underlying type.
    """

    template = "Invalid value '{value}' for param {param} of type {type_name}"
    status_code = HTTPStatus.BAD_REQUEST.value
