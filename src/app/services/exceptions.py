def _exception_from_packed_args(exception_cls, args=None, kwargs=None):
    # This is helpful for reducing Exceptions that only accept kwargs as
    # only positional arguments can be provided for __reduce__
    # Ideally, this would also be a class method on ServiceError
    # but instance methods cannot be pickled.
    if args is None:
        args = ()
    if kwargs is None:
        kwargs = {}
    return exception_cls(*args, **kwargs)


class ServiceError(Exception):
    """
    The base exception class for Service exceptions.

    :ivar msg: The descriptive message associated with the error.
    """

    fmt = "{msg}"

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        msg = self.fmt.format(**kwargs)
        super().__init__(self, msg)

    def __reduce__(self):
        return _exception_from_packed_args, (self.__class__, None, self.kwargs)


class VaultAuthenticationError(ServiceError):
    """
    :ivar username: Username.
    """

    fmt = "Vault authentication failed for user: {username}"


class VaultCredentialsError(ServiceError):
    """
    :ivar role_name: Vault role name.
    """

    fmt = "Vault credentials error for role: {role_name}"


class DataNotFoundError(ServiceError):
    """
    The data associated with a particular path could not be loaded.

    :ivar data_path: The data path that the user attempted to load.
    """

    fmt = "Unable to load data for: {data_path}"


class IdentityNotFoundError(DataNotFoundError):
    """
    Identity not found.

    :ivar identity_id: Entity id.
    """

    fmt = "Unable to find Identity with id: {identity_id}"


class IdentitySaveError(ServiceError):
    """
    Error saving Identity.

    :ivar infn_uuid: Infn UUID.
    """

    fmt = "Unable to save Identity with Infn UUID: {infn_uuid}"


class MissingParametersError(ServiceError):
    """
    One or more required parameters were not supplied.

    :ivar object: The object that has missing parameters.
        This can be an operation or a parameter (in the
        case of inner params).  The str() of this object
        will be used so it doesn't need to implement anything
        other than str().
    :ivar missing: The names of the missing parameters.
    """

    fmt = "The following required parameters are missing for {object_name}: {missing}"


class ValidationError(ServiceError):
    """
    An exception occurred validating parameters.

    Subclasses must accept a ``value`` and ``param``
    argument in their ``__init__``.

    :ivar value: The value that was being validated.
    :ivar param: The parameter that failed validation.
    :ivar type_name: The name of the underlying type.
    """

    fmt = "Invalid value ('{value}') for param {param} of type {type_name} "
