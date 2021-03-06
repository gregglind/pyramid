import os
import re
import sys
import threading
import inspect

import venusian

from translationstring import ChameleonTranslate

from zope.configuration import xmlconfig
from zope.configuration.config import ConfigurationMachine
from zope.configuration.xmlconfig import registerCommonDirectives

from zope.interface import Interface
from zope.interface import implementedBy
from zope.interface.interfaces import IInterface
from zope.interface import implements

from pyramid.interfaces import IAuthenticationPolicy
from pyramid.interfaces import IAuthorizationPolicy
from pyramid.interfaces import IChameleonTranslate
from pyramid.interfaces import IDebugLogger
from pyramid.interfaces import IDefaultPermission
from pyramid.interfaces import IDefaultRootFactory
from pyramid.interfaces import IException
from pyramid.interfaces import IExceptionResponse
from pyramid.interfaces import IExceptionViewClassifier
from pyramid.interfaces import ILocaleNegotiator
from pyramid.interfaces import IMultiView
from pyramid.interfaces import IPackageOverrides
from pyramid.interfaces import IRendererFactory
from pyramid.interfaces import IRendererGlobalsFactory
from pyramid.interfaces import IRequest
from pyramid.interfaces import IRequestFactory
from pyramid.interfaces import IRootFactory
from pyramid.interfaces import IRouteRequest
from pyramid.interfaces import IRoutesMapper
from pyramid.interfaces import ISecuredView
from pyramid.interfaces import ISessionFactory
from pyramid.interfaces import IStaticURLInfo
from pyramid.interfaces import ITranslationDirectories
from pyramid.interfaces import ITraverser
from pyramid.interfaces import IView
from pyramid.interfaces import IViewClassifier

try:
    from pyramid import chameleon_text
except TypeError:  # pragma: no cover
    chameleon_text = None # pypy
try: 
    from pyramid import chameleon_zpt
except TypeError: # pragma: no cover
    chameleon_zpt = None # pypy

from pyramid import renderers
from pyramid.authorization import ACLAuthorizationPolicy
from pyramid.compat import all
from pyramid.compat import md5
from pyramid.events import ApplicationCreated
from pyramid.exceptions import ConfigurationError
from pyramid.exceptions import Forbidden
from pyramid.exceptions import NotFound
from pyramid.exceptions import PredicateMismatch
from pyramid.i18n import get_localizer
from pyramid.log import make_stream_logger
from pyramid.mako_templating import renderer_factory as mako_renderer_factory
from pyramid.path import caller_package
from pyramid.path import package_path
from pyramid.registry import Registry
from pyramid.renderers import RendererHelper
from pyramid.request import route_request_iface
from pyramid.resource import PackageOverrides
from pyramid.resource import resolve_resource_spec
from pyramid.settings import Settings
from pyramid.static import StaticURLInfo
from pyramid.threadlocal import get_current_registry
from pyramid.threadlocal import get_current_request
from pyramid.threadlocal import manager
from pyramid.traversal import DefaultRootFactory
from pyramid.traversal import find_interface
from pyramid.traversal import traversal_path
from pyramid.urldispatch import RoutesMapper
from pyramid.util import DottedNameResolver
from pyramid.view import default_exceptionresponse_view
from pyramid.view import render_view_to_response

MAX_ORDER = 1 << 30
DEFAULT_PHASH = md5().hexdigest()

DEFAULT_RENDERERS = (
    ('.mak', mako_renderer_factory),
    ('.mako', mako_renderer_factory),
    ('json', renderers.json_renderer_factory),
    ('string', renderers.string_renderer_factory),
    )

if chameleon_text:
    DEFAULT_RENDERERS += (('.pt', chameleon_zpt.renderer_factory),)
if chameleon_zpt:
    DEFAULT_RENDERERS += (('.txt', chameleon_text.renderer_factory),)


class Configurator(object):
    """
    A Configurator is used to configure a :app:`Pyramid`
    :term:`application registry`.

    The Configurator accepts a number of arguments: ``registry``,
    ``package``, ``settings``, ``root_factory``,
    ``authentication_policy``, ``authorization_policy``, ``renderers``
    ``debug_logger``, ``locale_negotiator``, ``request_factory``, and
    ``renderer_globals_factory``.

    If the ``registry`` argument is passed as a non-``None`` value, it
    must be an instance of the :class:`pyramid.registry.Registry`
    class representing the registry to configure.  If ``registry`` is
    ``None``, the configurator will create a
    :class:`pyramid.registry.Registry` instance itself; it will
    also perform some default configuration that would not otherwise
    be done.  After construction, the configurator may be used to add
    configuration to the registry.  The overall state of a registry is
    called the 'configuration state'.

    .. warning:: If a ``registry`` is passed to the Configurator
       constructor, all other constructor arguments except ``package``
       are ignored.

    If the ``package`` argument is passed, it must be a reference to a
    Python :term:`package` (e.g. ``sys.modules['thepackage']``) or a
    :term:`dotted Python name` to same.  This value is used as a basis
    to convert relative paths passed to various configuration methods,
    such as methods which accept a ``renderer`` argument, into
    absolute paths.  If ``None`` is passed (the default), the package
    is assumed to be the Python package in which the *caller* of the
    ``Configurator`` constructor lives.

    If the ``settings`` argument is passed, it should be a Python dictionary
    representing the deployment settings for this application.  These are
    later retrievable using the :attr:`pyramid.registry.Registry.settings`
    attribute (aka ``request.registry.settings``).

    If the ``root_factory`` argument is passed, it should be an object
    representing the default :term:`root factory` for your application
    or a :term:`dotted Python name` to same.  If it is ``None``, a
    default root factory will be used.

    If ``authentication_policy`` is passed, it should be an instance
    of an :term:`authentication policy` or a :term:`dotted Python
    name` to same.

    If ``authorization_policy`` is passed, it should be an instance of
    an :term:`authorization policy` or a :term:`dotted Python name` to
    same.

    .. note:: A ``ConfigurationError`` will be raised when an
       authorization policy is supplied without also supplying an
       authentication policy (authorization requires authentication).

    If ``renderers`` is passed, it should be a list of tuples
    representing a set of :term:`renderer` factories which should be
    configured into this application (each tuple representing a set of
    positional values that should be passed to
    :meth:`pyramid.configuration.Configurator.add_renderer`).  If
    it is not passed, a default set of renderer factories is used.

    If ``debug_logger`` is not passed, a default debug logger that
    logs to stderr will be used.  If it is passed, it should be an
    instance of the :class:`logging.Logger` (PEP 282) standard library
    class or a :term:`dotted Python name` to same.  The debug logger
    is used by :app:`Pyramid` itself to log warnings and
    authorization debugging information.

    If ``locale_negotiator`` is passed, it should be a :term:`locale
    negotiator` implementation or a :term:`dotted Python name` to
    same.  See :ref:`custom_locale_negotiator`.

    If ``request_factory`` is passed, it should be a :term:`request
    factory` implementation or a :term:`dotted Python name` to same.
    See :ref:`custom_request_factory`.  By default it is ``None``,
    which means use the default request factory.

    If ``renderer_globals_factory`` is passed, it should be a
    :term:`renderer globals` factory implementation or a :term:`dotted
    Python name` to same.  See :ref:`custom_renderer_globals_factory`.
    By default, it is ``None``, which means use no renderer globals
    factory.

    If ``default_permission`` is passed, it should be a
    :term:`permission` string to be used as the default permission for
    all view configuration registrations performed against this
    Configurator.  An example of a permission string:``'view'``.
    Adding a default permission makes it unnecessary to protect each
    view configuration with an explicit permission, unless your
    application policy requires some exception for a particular view.
    By default, ``default_permission`` is ``None``, meaning that view
    configurations which do not explicitly declare a permission will
    always be executable by entirely anonymous users (any
    authorization policy in effect is ignored).  See also
    :ref:`setting_a_default_permission`.

    If ``session_factory`` is passed, it should be an object which
    implements the :term:`session factory` interface.  If a nondefault
    value is passed, the ``session_factory`` will be used to create a
    session object when ``request.session`` is accessed.  Note that
    the same outcome can be achieved by calling
    :ref:`pyramid.configration.Configurator.set_session_factory`.  By
    default, this argument is ``None``, indicating that no session
    factory will be configured (and thus accessing ``request.session``
    will throw an error) unless ``set_session_factory`` is called later
    during configuration.  """

    manager = manager # for testing injection
    venusian = venusian # for testing injection

    def __init__(self,
                 registry=None,
                 package=None,
                 settings=None,
                 root_factory=None,
                 authentication_policy=None,
                 authorization_policy=None,
                 renderers=DEFAULT_RENDERERS,
                 debug_logger=None,
                 locale_negotiator=None,
                 request_factory=None,
                 renderer_globals_factory=None,
                 default_permission=None,
                 session_factory=None,
                 ):
        if package is None:
            package = caller_package()
        name_resolver = DottedNameResolver(package)
        self.name_resolver = name_resolver
        self.package_name = name_resolver.package_name
        self.package = name_resolver.package
        self.registry = registry
        if registry is None:
            registry = Registry(self.package_name)
            self.registry = registry
            self.setup_registry(
                settings=settings,
                root_factory=root_factory,
                authentication_policy=authentication_policy,
                authorization_policy=authorization_policy,
                renderers=renderers,
                debug_logger=debug_logger,
                locale_negotiator=locale_negotiator,
                request_factory=request_factory,
                renderer_globals_factory=renderer_globals_factory,
                default_permission=default_permission,
                session_factory=session_factory,
                )

    def _set_settings(self, mapping):
        settings = Settings(mapping or {})
        self.registry.settings = settings
        return settings

    def _set_root_factory(self, factory):
        """ Add a :term:`root factory` to the current configuration
        state.  If the ``factory`` argument is ``None`` a default root
        factory will be registered."""
        factory = self.maybe_dotted(factory)
        if factory is None:
            factory = DefaultRootFactory
        self.registry.registerUtility(factory, IRootFactory)
        self.registry.registerUtility(factory, IDefaultRootFactory) # b/c

    def _set_authentication_policy(self, policy, _info=u''):
        """ Add a :app:`Pyramid` :term:`authentication policy` to
        the current configuration."""
        policy = self.maybe_dotted(policy)
        self.registry.registerUtility(policy, IAuthenticationPolicy,
                                      info=_info)

    def _set_authorization_policy(self, policy, _info=u''):
        """ Add a :app:`Pyramid` :term:`authorization policy` to
        the current configuration state (also accepts a :term:`dotted
        Python name`."""
        policy = self.maybe_dotted(policy)
        self.registry.registerUtility(policy, IAuthorizationPolicy, info=_info)

    def _make_spec(self, path_or_spec):
        package, filename = resolve_resource_spec(path_or_spec,
                                                  self.package_name)
        if package is None:
            return filename # absolute filename
        return '%s:%s' % (package, filename)

    def _split_spec(self, path_or_spec):
        return resolve_resource_spec(path_or_spec, self.package_name)

    def _derive_view(self, view, permission=None, predicates=(),
                     attr=None, renderer=None, wrapper_viewname=None,
                     viewname=None, accept=None, order=MAX_ORDER,
                     phash=DEFAULT_PHASH):
        if renderer is None: # use default renderer if one exists
            default_renderer_factory = self.registry.queryUtility(
                IRendererFactory)
            if default_renderer_factory is not None:
                renderer = {'name':None, 'package':self.package}
        view = self.maybe_dotted(view)
        authn_policy = self.registry.queryUtility(IAuthenticationPolicy)
        authz_policy = self.registry.queryUtility(IAuthorizationPolicy)
        settings = self.registry.settings
        logger = self.registry.queryUtility(IDebugLogger)
        mapped_view = _map_view(view, self.registry, attr, renderer)
        owrapped_view = _owrap_view(mapped_view, viewname, wrapper_viewname)
        secured_view = _secure_view(owrapped_view, permission,
                                    authn_policy, authz_policy)
        debug_view = _authdebug_view(secured_view, permission,
                                     authn_policy, authz_policy, settings,
                                     logger)
        predicated_view = _predicate_wrap(debug_view, predicates)
        derived_view = _attr_wrap(predicated_view, accept, order, phash)
        return derived_view

    def _override(self, package, path, override_package, override_prefix,
                  _info=u'', PackageOverrides=PackageOverrides):
            pkg_name = package.__name__
            override_pkg_name = override_package.__name__
            override = self.registry.queryUtility(
                IPackageOverrides, name=pkg_name)
            if override is None:
                override = PackageOverrides(package)
                self.registry.registerUtility(override, IPackageOverrides,
                                              name=pkg_name, info=_info)
            override.insert(path, override_pkg_name, override_prefix)

    def _set_security_policies(self, authentication, authorization=None):
        if authorization is None:
            authorization = ACLAuthorizationPolicy() # default
        if authorization and not authentication:
            raise ConfigurationError(
                'If the "authorization" is passed a value, '
                'the "authentication" argument must also be '
                'passed a value; authorization requires authentication.')
        self._set_authentication_policy(authentication)
        self._set_authorization_policy(authorization)

    def _fix_registry(self):
        """ Fix up a ZCA component registry that is not a
        pyramid.registry.Registry by adding analogues of ``has_listeners``,
        and ``notify`` through monkey-patching."""

        _registry = self.registry

        if not hasattr(_registry, 'notify'):
            def notify(*events):
                [ _ for _ in _registry.subscribers(events, None) ]
            _registry.notify = notify

        if not hasattr(_registry, 'has_listeners'):
            _registry.has_listeners = True

    # API

    def with_package(self, package):
        """ Return a new Configurator instance with the same registry
        as this configurator using the package supplied as the
        ``package`` argument to the new configurator.  ``package`` may
        be an actual Python package object or a Python dotted name
        representing a package."""
        return self.__class__(registry=self.registry, package=package)

    def maybe_dotted(self, dotted):
        """ Resolve the :term:`dotted Python name` ``dotted`` to a
        global Python object.  If ``dotted`` is not a string, return
        it without attempting to do any name resolution.  If
        ``dotted`` is a relative dotted name (e.g. ``.foo.bar``,
        consider it relative to the ``package`` argument supplied to
        this Configurator's constructor."""
        return self.name_resolver.maybe_resolve(dotted)

    def absolute_resource_spec(self, relative_spec):
        """ Resolve the potentially relative :term:`resource
        specification` string passed as ``relative_spec`` into an
        absolute resource specification string and return the string.
        Use the ``package`` of this configurator as the package to
        which the resource specification will be considered relative
        when generating an absolute resource specification.  If the
        provided ``relative_spec`` argument is already absolute, or if
        the ``relative_spec`` is not a string, it is simply returned."""
        if not isinstance(relative_spec, basestring):
            return relative_spec
        return self._make_spec(relative_spec)

    def setup_registry(self, settings=None, root_factory=None,
                       authentication_policy=None, authorization_policy=None,
                       renderers=DEFAULT_RENDERERS, debug_logger=None,
                       locale_negotiator=None, request_factory=None,
                       renderer_globals_factory=None,
                       default_permission=None,
                       session_factory=None):
        """ When you pass a non-``None`` ``registry`` argument to the
        :term:`Configurator` constructor, no initial 'setup' is
        performed against the registry.  This is because the registry
        you pass in may have already been initialized for use under
        :app:`Pyramid` via a different configurator.  However, in
        some circumstances, such as when you want to use the Zope
        'global` registry instead of a registry created as a result of
        the Configurator constructor, or when you want to reset the
        initial setup of a registry, you *do* want to explicitly
        initialize the registry associated with a Configurator for use
        under :app:`Pyramid`.  Use ``setup_registry`` to do this
        initialization.

        ``setup_registry`` configures settings, a root factory,
        security policies, renderers, a debug logger, a locale
        negotiator, and various other settings using the
        configurator's current registry, as per the descriptions in
        the Configurator constructor."""
        self._fix_registry()
        self._set_settings(settings)
        self._set_root_factory(root_factory)
        debug_logger = self.maybe_dotted(debug_logger)
        if debug_logger is None:
            debug_logger = make_stream_logger('pyramid.debug', sys.stderr)
        registry = self.registry
        registry.registerUtility(debug_logger, IDebugLogger)
        if authentication_policy or authorization_policy:
            self._set_security_policies(authentication_policy,
                                        authorization_policy)
        for name, renderer in renderers:
            self.add_renderer(name, renderer)
        self.add_view(default_exceptionresponse_view,
                      context=IExceptionResponse)
        if locale_negotiator:
            locale_negotiator = self.maybe_dotted(locale_negotiator)
            registry.registerUtility(locale_negotiator, ILocaleNegotiator)
        if request_factory:
            request_factory = self.maybe_dotted(request_factory)
            self.set_request_factory(request_factory)
        if renderer_globals_factory:
            renderer_globals_factory = self.maybe_dotted(
                renderer_globals_factory)
            self.set_renderer_globals_factory(renderer_globals_factory)
        if default_permission:
            self.set_default_permission(default_permission)
        if session_factory is not None:
            self.set_session_factory(session_factory)

    # getSiteManager is a unit testing dep injection
    def hook_zca(self, getSiteManager=None):
        """ Call :func:`zope.component.getSiteManager.sethook` with
        the argument
        :data:`pyramid.threadlocal.get_current_registry`, causing
        the :term:`Zope Component Architecture` 'global' APIs such as
        :func:`zope.component.getSiteManager`,
        :func:`zope.component.getAdapter` and others to use the
        :app:`Pyramid` :term:`application registry` rather than the
        Zope 'global' registry.  If :mod:`zope.component` cannot be
        imported, this method will raise an :exc:`ImportError`."""
        if getSiteManager is None:
            from zope.component import getSiteManager
        getSiteManager.sethook(get_current_registry)

    # getSiteManager is a unit testing dep injection
    def unhook_zca(self, getSiteManager=None):
        """ Call :func:`zope.component.getSiteManager.reset` to undo
        the action of
        :meth:`pyramid.configuration.Configurator.hook_zca`.  If
        :mod:`zope.component` cannot be imported, this method will
        raise an :exc:`ImportError`."""
        if getSiteManager is None: # pragma: no cover
            from zope.component import getSiteManager
        getSiteManager.reset()

    def begin(self, request=None):
        """ Indicate that application or test configuration has begun.
        This pushes a dictionary containing the :term:`application
        registry` implied by ``registry`` attribute of this
        configurator and the :term:`request` implied by the
        ``request`` argument on to the :term:`thread local` stack
        consulted by various :mod:`pyramid.threadlocal` API
        functions."""
        self.manager.push({'registry':self.registry, 'request':request})

    def end(self):
        """ Indicate that application or test configuration has ended.
        This pops the last value pushed on to the :term:`thread local`
        stack (usually by the ``begin`` method) and returns that
        value.
        """
        return self.manager.pop()

    def derive_view(self, view, attr=None, renderer=None):
        """

        Create a :term:`view callable` using the function, instance,
        or class (or :term:`dotted Python name` referring to the same)
        provided as ``view`` object.

        This is API is useful to framework extenders who create
        pluggable systems which need to register 'proxy' view
        callables for functions, instances, or classes which meet the
        requirements of being a :app:`Pyramid` view callable.  For
        example, a ``some_other_framework`` function in another
        framework may want to allow a user to supply a view callable,
        but he may want to wrap the view callable in his own before
        registering the wrapper as a :app:`Pyramid` view callable.
        Because a :app:`Pyramid` view callable can be any of a
        number of valid objects, the framework extender will not know
        how to call the user-supplied object.  Running it through
        ``derive_view`` normalizes it to a callable which accepts two
        arguments: ``context`` and ``request``.

        For example:

        .. code-block:: python

           def some_other_framework(user_supplied_view):
               config = Configurator(reg)
               proxy_view = config.derive_view(user_supplied_view)
               def my_wrapper(context, request):
                   do_something_that_mutates(request)
                   return proxy_view(context, request)
               config.add_view(my_wrapper)

        The ``view`` object provided should be one of the following:

        - A function or another non-class callable object that accepts
          a :term:`request` as a single positional argument and which
          returns a :term:`response` object.

        - A function or other non-class callable object that accepts
          two positional arguments, ``context, request`` and which
          returns a :term:`response` object.

        - A class which accepts a single positional argument in its
          constructor named ``request``, and which has a ``__call__``
          method that accepts no arguments that returns a
          :term:`response` object.

        - A class which accepts two positional arguments named
          ``context, request``, and which has a ``__call__`` method
          that accepts no arguments that returns a :term:`response`
          object.

        - A :term:`dotted Python name` which refers to any of the
          kinds of objects above.

        This API returns a callable which accepts the arguments
        ``context, request`` and which returns the result of calling
        the provided ``view`` object.

        The ``attr`` keyword argument is most useful when the view
        object is a class.  It names the method that should be used as
        the callable.  If ``attr`` is not provided, the attribute
        effectively defaults to ``__call__``.  See
        :ref:`class_as_view` for more information.

        The ``renderer`` keyword argument should be a renderer
        name. If supplied, it will cause the returned callable to use
        a :term:`renderer` to convert the user-supplied view result to
        a :term:`response` object.  If a ``renderer`` argument is not
        supplied, the user-supplied view must itself return a
        :term:`response` object.  """

        if renderer is not None and not isinstance(renderer, dict):
            renderer = {'name':renderer, 'package':self.package}
        return self._derive_view(view, attr=attr, renderer=renderer)

    def add_subscriber(self, subscriber, iface=None, info=u''):
        """Add an event :term:`subscriber` for the event stream
        implied by the supplied ``iface`` interface.  The
        ``subscriber`` argument represents a callable object (or a
        :term:`dotted Python name` which identifies a callable); it
        will be called with a single object ``event`` whenever
        :app:`Pyramid` emits an :term:`event` associated with the
        ``iface``, which may be an :term:`interface` or a class or a
        :term:`dotted Python name` to a global object representing an
        interface or a class.  Using the default ``iface`` value,
        ``None`` will cause the subscriber to be registered for all
        event types. See :ref:`events_chapter` for more information
        about events and subscribers."""
        dotted = self.maybe_dotted
        subscriber, iface = dotted(subscriber), dotted(iface)
        if iface is None:
            iface = (Interface,)
        if not isinstance(iface, (tuple, list)):
            iface = (iface,)
        self.registry.registerHandler(subscriber, iface, info=info)
        return subscriber

    def add_settings(self, settings=None, **kw):
        """Augment the ``settings`` argument passed in to the Configurator
        constructor with one or more 'setting' key/value pairs.  A setting is
        a single key/value pair in the dictionary-ish object returned from
        the API :attr:`pyramid.registry.Registry.settings` and
        :meth:`pyramid.configuration.Configurator.get_settings`.

        You may pass a dictionary::

           config.add_settings({'external_uri':'http://example.com'})

        Or a set of key/value pairs::

           config.add_settings(external_uri='http://example.com')

        This function is useful when you need to test code that accesses the
        :attr:`pyramid.registry.Registry.settings` API (or the
        :meth:`pyramid.configuration.Configurator.get_settings` API) and
        which uses values from that API.
        """
        if settings is None:
            settings = {}
        utility = self.registry.settings
        if utility is None:
            utility = self._set_settings(settings)
        utility.update(settings)
        utility.update(kw)

    def get_settings(self):
        """
        Return a 'settings' object for the current application.  A
        'settings' object is a dictionary-like object that contains
        key/value pairs based on the dictionary passed as the ``settings``
        argument to the :class:`pyramid.configuration.Configurator`
        constructor or the :func:`pyramid.router.make_app` API.

        .. note:: For backwards compatibility, dictionary keys can also be
           looked up as attributes of the settings object.

        .. note:: the :attr:`pyramid.registry.Registry.settings` API
           performs the same duty.
           """
        return self.registry.settings

    def make_wsgi_app(self):
        """ Returns a :app:`Pyramid` WSGI application representing
        the current configuration state and sends a
        :class:`pyramid.events.ApplicationCreated`
        event to all listeners."""
        from pyramid.router import Router # avoid circdep
        app = Router(self.registry)
        # We push the registry on to the stack here in case any code
        # that depends on the registry threadlocal APIs used in
        # listeners subscribed to the IApplicationCreated event.
        self.manager.push({'registry':self.registry, 'request':None})
        try:
            self.registry.notify(ApplicationCreated(app))
        finally:
            self.manager.pop()
        return app

    def load_zcml(self, spec='configure.zcml', lock=threading.Lock()):
        """ Load configuration from a :term:`ZCML` file into the
        current configuration state.  The ``spec`` argument is an
        absolute filename, a relative filename, or a :term:`resource
        specification`, defaulting to ``configure.zcml`` (relative to
        the package of the configurator's caller)."""
        package_name, filename = self._split_spec(spec)
        if package_name is None: # absolute filename
            package = self.package
        else:
            __import__(package_name)
            package = sys.modules[package_name]

        lock.acquire()
        self.manager.push({'registry':self.registry, 'request':None})
        try:
            context = ConfigurationMachine()
            registerCommonDirectives(context)
            context.package = package
            context.registry = self.registry
            xmlconfig.file(filename, package, context=context, execute=True)
        finally:
            lock.release()
            self.manager.pop()
        return self.registry

    def add_handler(self, route_name, pattern, handler, action=None, **kw):

        """ Add a Pylons-style view handler.  This function adds a
        route and some number of views based on a handler object
        (usually a class).

        ``route_name`` is the name of the route (to be used later in
        URL generation).

        ``pattern`` is the matching pattern,
        e.g. ``'/blog/{action}'``.  ``pattern`` may be ``None``, in
        which case the pattern of an existing route named the same as
        ``route_name`` is used.  If ``pattern`` is ``None`` and no
        route named ``route_name`` exists, a ``ConfigurationError`` is
        raised.

        ``handler`` is a dotted name of (or direct reference to) a
        Python handler class,
        e.g. ``'my.package.handlers.MyHandler'``.

        If ``{action}`` or ``:action`` is in
        the pattern, the exposed methods of the handler will be used
        as views.

        If ``action`` is passed, it will be considered the method name
        of the handler to use as a view.

        Passing both ``action`` and having an ``{action}`` in the
        route pattern is disallowed.

        Any extra keyword arguments are passed along to ``add_route``.

        See :ref:`handlers_chapter` for more explanatory documentation.

        This method returns the result of add_route."""
        handler = self.maybe_dotted(handler)

        if pattern is not None:
            route = self.add_route(route_name, pattern, **kw)
        else:
            mapper = self.get_routes_mapper()
            route = mapper.get_route(route_name)
            if route is None:
                raise ConfigurationError(
                    'The "pattern" parameter may only be "None" when a route '
                    'with the route_name argument was previously registered. '
                    'No such route named %r exists' % route_name)

            pattern = route.pattern

        path_has_action = ':action' in pattern or '{action}' in pattern

        if action and path_has_action:
            raise ConfigurationError(
                'action= (%r) disallowed when an action is in the route '
                'path %r' % (action, pattern))

        if path_has_action:
            autoexpose = getattr(handler, '__autoexpose__', r'[A-Za-z]+')
            if autoexpose:
                try:
                    autoexpose = re.compile(autoexpose).match
                except (re.error, TypeError), why:
                    raise ConfigurationError(why[0])
            for method_name, method in inspect.getmembers(
                handler, inspect.ismethod):
                configs = getattr(method, '__exposed__', [])
                if autoexpose and not configs:
                    if autoexpose(method_name):
                        configs = [{}]
                for expose_config in configs:
                    # we don't want to mutate any dict in __exposed__,
                    # so we copy each
                    view_args = expose_config.copy()
                    action = view_args.pop('name', method_name)
                    preds = list(view_args.pop('custom_predicates', []))
                    preds.append(ActionPredicate(action))
                    view_args['custom_predicates'] = preds
                    self.add_view(view=handler, attr=method_name,
                                  route_name=route_name, **view_args)
        else:
            method_name = action
            if method_name is None:
                method_name = '__call__'

            # Scan the controller for any other methods with this action name
            for meth_name, method in inspect.getmembers(
                handler, inspect.ismethod):
                configs = getattr(method, '__exposed__', [{}])
                for expose_config in configs:
                    # Don't re-register the same view if this method name is
                    # the action name
                    if meth_name == action:
                        continue
                    # We only reg a view if the name matches the action
                    if expose_config.get('name') != method_name:
                        continue
                    # we don't want to mutate any dict in __exposed__,
                    # so we copy each
                    view_args = expose_config.copy()
                    del view_args['name']
                    self.add_view(view=handler, attr=meth_name,
                                  route_name=route_name, **view_args)

            # Now register the method itself
            method = getattr(handler, method_name, None)
            configs = getattr(method, '__exposed__', [{}])
            for expose_config in configs:
                self.add_view(view=handler, attr=action, route_name=route_name,
                              **expose_config)

        return route

    def add_view(self, view=None, name="", for_=None, permission=None,
                 request_type=None, route_name=None, request_method=None,
                 request_param=None, containment=None, attr=None,
                 renderer=None, wrapper=None, xhr=False, accept=None,
                 header=None, path_info=None, custom_predicates=(),
                 context=None, _info=u''):
        """ Add a :term:`view configuration` to the current
        configuration state.  Arguments to ``add_view`` are broken
        down below into *predicate* arguments and *non-predicate*
        arguments.  Predicate arguments narrow the circumstances in
        which the view callable will be invoked when a request is
        presented to :app:`Pyramid`; non-predicate arguments are
        informational.

        Non-Predicate Arguments

        view

          A :term:`view callable` or a :term:`dotted Python name`
          which refers to a view callable.  This argument is required
          unless a ``renderer`` argument also exists.  If a
          ``renderer`` argument is passed, and a ``view`` argument is
          not provided, the view callable defaults to a callable that
          returns an empty dictionary (see
          :ref:`views_which_use_a_renderer`).

        permission

          The name of a :term:`permission` that the user must possess
          in order to invoke the :term:`view callable`.  See
          :ref:`view_security_section` for more information about view
          security and permissions.  If ``permission`` is omitted, a
          *default* permission may be used for this view registration
          if one was named as the
          :class:`pyramid.configuration.Configurator` constructor's
          ``default_permission`` argument, or if
          :meth:`pyramid.configuration.Configurator.set_default_permission`
          was used prior to this view registration.  Pass the string
          ``__no_permission_required__`` as the permission argument to
          explicitly indicate that the view should always be
          executable by entirely anonymous users, regardless of the
          default permission, bypassing any :term:`authorization
          policy` that may be in effect.

        attr

          The view machinery defaults to using the ``__call__`` method
          of the :term:`view callable` (or the function itself, if the
          view callable is a function) to obtain a response.  The
          ``attr`` value allows you to vary the method attribute used
          to obtain the response.  For example, if your view was a
          class, and the class has a method named ``index`` and you
          wanted to use this method instead of the class' ``__call__``
          method to return the response, you'd say ``attr="index"`` in the
          view configuration for the view.  This is
          most useful when the view definition is a class.

        renderer

          This is either a single string term (e.g. ``json``) or a
          string implying a path or :term:`resource specification`
          (e.g. ``templates/views.pt``) naming a :term:`renderer`
          implementation.  If the ``renderer`` value does not contain
          a dot ``.``, the specified string will be used to look up a
          renderer implementation, and that renderer implementation
          will be used to construct a response from the view return
          value.  If the ``renderer`` value contains a dot (``.``),
          the specified term will be treated as a path, and the
          filename extension of the last element in the path will be
          used to look up the renderer implementation, which will be
          passed the full path.  The renderer implementation will be
          used to construct a :term:`response` from the view return
          value.

          Note that if the view itself returns a :term:`response` (see
          :ref:`the_response`), the specified renderer implementation
          is never called.

          When the renderer is a path, although a path is usually just
          a simple relative pathname (e.g. ``templates/foo.pt``,
          implying that a template named "foo.pt" is in the
          "templates" directory relative to the directory of the
          current :term:`package` of the Configurator), a path can be
          absolute, starting with a slash on UNIX or a drive letter
          prefix on Windows.  The path can alternately be a
          :term:`resource specification` in the form
          ``some.dotted.package_name:relative/path``, making it
          possible to address template resources which live in a
          separate package.

          The ``renderer`` attribute is optional.  If it is not
          defined, the "null" renderer is assumed (no rendering is
          performed and the value is passed back to the upstream
          :app:`Pyramid` machinery unmolested).

        wrapper

          The :term:`view name` of a different :term:`view
          configuration` which will receive the response body of this
          view as the ``request.wrapped_body`` attribute of its own
          :term:`request`, and the :term:`response` returned by this
          view as the ``request.wrapped_response`` attribute of its
          own request.  Using a wrapper makes it possible to "chain"
          views together to form a composite response.  The response
          of the outermost wrapper view will be returned to the user.
          The wrapper view will be found as any view is found: see
          :ref:`view_lookup`.  The "best" wrapper view will be found
          based on the lookup ordering: "under the hood" this wrapper
          view is looked up via
          ``pyramid.view.render_view_to_response(context, request,
          'wrapper_viewname')``. The context and request of a wrapper
          view is the same context and request of the inner view.  If
          this attribute is unspecified, no view wrapping is done.

        Predicate Arguments

        name

          The :term:`view name`.  Read :ref:`traversal_chapter` to
          understand the concept of a view name.

        context

          An object or a :term:`dotted Python name` referring to an
          interface or class object that the :term:`context` must be
          an instance of, *or* the :term:`interface` that the
          :term:`context` must provide in order for this view to be
          found and called.  This predicate is true when the
          :term:`context` is an instance of the represented class or
          if the :term:`context` provides the represented interface;
          it is otherwise false.  This argument may also be provided
          to ``add_view`` as ``for_`` (an older, still-supported
          spelling).

        route_name

          This value must match the ``name`` of a :term:`route
          configuration` declaration (see :ref:`urldispatch_chapter`)
          that must match before this view will be called.  Note that
          the ``route`` configuration referred to by ``route_name``
          usually has a ``*traverse`` token in the value of its
          ``path``, representing a part of the path that will be used
          by :term:`traversal` against the result of the route's
          :term:`root factory`.

          .. warning:: Using this argument services an advanced
             feature that isn't often used unless you want to perform
             traversal *after* a route has matched. See
             :ref:`hybrid_chapter` for more information on using this
             advanced feature.

        request_type

          This value should be an :term:`interface` that the
          :term:`request` must provide in order for this view to be
          found and called.  This value exists only for backwards
          compatibility purposes.

        request_method

          This value can either be one of the strings ``GET``,
          ``POST``, ``PUT``, ``DELETE``, or ``HEAD`` representing an
          HTTP ``REQUEST_METHOD``.  A view declaration with this
          argument ensures that the view will only be called when the
          request's ``method`` attribute (aka the ``REQUEST_METHOD`` of
          the WSGI environment) string matches the supplied value.

        request_param

          This value can be any string.  A view declaration with this
          argument ensures that the view will only be called when the
          :term:`request` has a key in the ``request.params``
          dictionary (an HTTP ``GET`` or ``POST`` variable) that has a
          name which matches the supplied value.  If the value
          supplied has a ``=`` sign in it,
          e.g. ``request_params="foo=123"``, then the key (``foo``)
          must both exist in the ``request.params`` dictionary, *and*
          the value must match the right hand side of the expression
          (``123``) for the view to "match" the current request.

        containment

          This value should be a Python class or :term:`interface` or
          a :term:`dotted Python name` to such an object that a parent
          object in the :term:`lineage` must provide in order for this
          view to be found and called.  The nodes in your object graph
          must be "location-aware" to use this feature.  See
          :ref:`location_aware` for more information about
          location-awareness.

        xhr

          This value should be either ``True`` or ``False``.  If this
          value is specified and is ``True``, the :term:`request`
          must possess an ``HTTP_X_REQUESTED_WITH`` (aka
          ``X-Requested-With``) header that has the value
          ``XMLHttpRequest`` for this view to be found and called.
          This is useful for detecting AJAX requests issued from
          jQuery, Prototype and other Javascript libraries.

        accept

          The value of this argument represents a match query for one
          or more mimetypes in the ``Accept`` HTTP request header.  If
          this value is specified, it must be in one of the following
          forms: a mimetype match token in the form ``text/plain``, a
          wildcard mimetype match token in the form ``text/*`` or a
          match-all wildcard mimetype match token in the form ``*/*``.
          If any of the forms matches the ``Accept`` header of the
          request, this predicate will be true.

        header

          This value represents an HTTP header name or a header
          name/value pair.  If the value contains a ``:`` (colon), it
          will be considered a name/value pair
          (e.g. ``User-Agent:Mozilla/.*`` or ``Host:localhost``).  The
          value portion should be a regular expression.  If the value
          does not contain a colon, the entire value will be
          considered to be the header name
          (e.g. ``If-Modified-Since``).  If the value evaluates to a
          header name only without a value, the header specified by
          the name must be present in the request for this predicate
          to be true.  If the value evaluates to a header name/value
          pair, the header specified by the name must be present in
          the request *and* the regular expression specified as the
          value must match the header value.  Whether or not the value
          represents a header name or a header name/value pair, the
          case of the header name is not significant.

        path_info

          This value represents a regular expression pattern that will
          be tested against the ``PATH_INFO`` WSGI environment
          variable.  If the regex matches, this predicate will be
          ``True``.


        custom_predicates

          This value should be a sequence of references to custom
          predicate callables.  Use custom predicates when no set of
          predefined predicates do what you need.  Custom predicates
          can be combined with predefined predicates as necessary.
          Each custom predicate callable should accept two arguments:
          ``context`` and ``request`` and should return either
          ``True`` or ``False`` after doing arbitrary evaluation of
          the context and/or the request.  If all callables return
          ``True``, the associated view callable will be considered
          viable for a given request.

          """
        view = self.maybe_dotted(view)
        context = self.maybe_dotted(context)
        for_ = self.maybe_dotted(for_)
        containment = self.maybe_dotted(containment)

        if not view:
            if renderer:
                def view(context, request):
                    return {}
            else:
                raise ConfigurationError('"view" was not specified and '
                                         'no "renderer" specified')

        if request_type is not None:
            request_type = self.maybe_dotted(request_type)
            if not IInterface.providedBy(request_type):
                raise ConfigurationError(
                    'request_type must be an interface, not %s' % request_type)

        request_iface = IRequest

        if route_name is not None:
            request_iface = self.registry.queryUtility(IRouteRequest,
                                                       name=route_name)
            if request_iface is None:
                deferred_views = getattr(self.registry,
                                         'deferred_route_views', None)
                if deferred_views is None:
                    deferred_views = self.registry.deferred_route_views = {}
                info = dict(
                    view=view, name=name, for_=for_, permission=permission,
                    request_type=request_type, route_name=route_name,
                    request_method=request_method, request_param=request_param,
                    containment=containment, attr=attr,
                    renderer=renderer, wrapper=wrapper, xhr=xhr, accept=accept,
                    header=header, path_info=path_info,
                    custom_predicates=custom_predicates, context=context,
                    _info=u''
                    )
                view_info = deferred_views.setdefault(route_name, [])
                view_info.append(info)
                return

        order, predicates, phash = _make_predicates(xhr=xhr,
            request_method=request_method, path_info=path_info,
            request_param=request_param, header=header, accept=accept,
            containment=containment, request_type=request_type,
            custom=custom_predicates)

        if permission is None:
            # intent: will be None if no default permission is registered
            permission = self.registry.queryUtility(IDefaultPermission)

        if renderer is not None and not isinstance(renderer, dict):
            renderer = {'name':renderer, 'package':self.package}

        # NO_PERMISSION_REQUIRED handled by _secure_view
        derived_view = self._derive_view(view, permission, predicates, attr,
                                         renderer, wrapper, name, accept,
                                         order, phash)

        if context is None:
            context = for_

        r_context = context
        if r_context is None:
            r_context = Interface
        if not IInterface.providedBy(r_context):
            r_context = implementedBy(r_context)

        registered = self.registry.adapters.registered

        # A multiviews is a set of views which are registered for
        # exactly the same context type/request type/name triad.  Each
        # consituent view in a multiview differs only by the
        # predicates which it possesses.

        # To find a previously registered view for a context
        # type/request type/name triad, we need to use the
        # ``registered`` method of the adapter registry rather than
        # ``lookup``.  ``registered`` ignores interface inheritance
        # for the required and provided arguments, returning only a
        # view registered previously with the *exact* triad we pass
        # in.

        # We need to do this three times, because we use three
        # different interfaces as the ``provided`` interface while
        # doing registrations, and ``registered`` performs exact
        # matches on all the arguments it receives.

        old_view = None

        for view_type in (IView, ISecuredView, IMultiView):
            old_view = registered((IViewClassifier, request_iface, r_context),
                                  view_type, name)
            if old_view is not None:
                break

        isexc = isexception(context)

        def regclosure():
            if hasattr(derived_view, '__call_permissive__'):
                view_iface = ISecuredView
            else:
                view_iface = IView
            self.registry.registerAdapter(
                derived_view,
                (IViewClassifier, request_iface, context),
                view_iface, name, info=_info)
            if isexc:
                self.registry.registerAdapter(
                    derived_view,
                    (IExceptionViewClassifier, request_iface, context),
                    view_iface, name, info=_info)

        is_multiview = IMultiView.providedBy(old_view)
        old_phash = getattr(old_view, '__phash__', DEFAULT_PHASH)

        if old_view is None:
            # - No component was yet registered for any of our I*View
            #   interfaces exactly; this is the first view for this
            #   triad.
            regclosure()

        elif (not is_multiview) and (old_phash == phash):
            # - A single view component was previously registered with
            #   the same predicate hash as this view; this registration
            #   is therefore an override.
            regclosure()

        else:
            # - A view or multiview was already registered for this
            #   triad, and the new view is not an override.

            # XXX we could try to be more efficient here and register
            # a non-secured view for a multiview if none of the
            # multiview's consituent views have a permission
            # associated with them, but this code is getting pretty
            # rough already
            if is_multiview:
                multiview = old_view
            else:
                multiview = MultiView(name)
                old_accept = getattr(old_view, '__accept__', None)
                old_order = getattr(old_view, '__order__', MAX_ORDER)
                multiview.add(old_view, old_order, old_accept, old_phash)
            multiview.add(derived_view, order, accept, phash)
            for view_type in (IView, ISecuredView):
                # unregister any existing views
                self.registry.adapters.unregister(
                    (IViewClassifier, request_iface, r_context),
                    view_type, name=name)
                if isexc:
                    self.registry.adapters.unregister(
                        (IExceptionViewClassifier, request_iface, r_context),
                        view_type, name=name)
            self.registry.registerAdapter(
                multiview,
                (IViewClassifier, request_iface, context),
                IMultiView, name=name, info=_info)
            if isexc:
                self.registry.registerAdapter(
                    multiview,
                    (IExceptionViewClassifier, request_iface, context),
                    IMultiView, name=name, info=_info)

    def add_route(self,
                  name,
                  pattern=None,
                  view=None,
                  view_for=None,
                  permission=None,
                  factory=None,
                  for_=None,
                  header=None,
                  xhr=False,
                  accept=None,
                  path_info=None,
                  request_method=None,
                  request_param=None,
                  traverse=None,
                  custom_predicates=(),
                  view_permission=None,
                  renderer=None,
                  view_renderer=None,
                  view_context=None,
                  view_attr=None,
                  use_global_views=False,
                  path=None,
                  pregenerator=None,
                  _info=u''):
        """ Add a :term:`route configuration` to the current
        configuration state, as well as possibly a :term:`view
        configuration` to be used to specify a :term:`view callable`
        that will be invoked when this route matches.  The arguments
        to this method are divided into *predicate*, *non-predicate*,
        and *view-related* types.  :term:`Route predicate` arguments
        narrow the circumstances in which a route will be match a
        request; non-predicate arguments are informational.

        Non-Predicate Arguments

        name

          The name of the route, e.g. ``myroute``.  This attribute is
          required.  It must be unique among all defined routes in a given
          application.

        factory

          A Python object (often a function or a class) or a
          :term:`dotted Python name` which refers to the same object
          that will generate a :app:`Pyramid` :term:`context`
          object when this route matches. For example,
          ``mypackage.models.MyFactoryClass``.  If this argument is
          not specified, a default root factory will be used.

        traverse

          If you would like to cause the :term:`context` to be
          something other than the :term:`root` object when this route
          matches, you can spell a traversal pattern as the
          ``traverse`` argument.  This traversal pattern will be used
          as the traversal path: traversal will begin at the root
          object implied by this route (either the global root, or the
          object returned by the ``factory`` associated with this
          route).

          The syntax of the ``traverse`` argument is the same as it is
          for ``pattern``. For example, if the ``pattern`` provided to
          ``add_route`` is ``articles/{article}/edit``, and the
          ``traverse`` argument provided to ``add_route`` is
          ``/{article}``, when a request comes in that causes the route
          to match in such a way that the ``article`` match value is
          '1' (when the request URI is ``/articles/1/edit``), the
          traversal path will be generated as ``/1``.  This means that
          the root object's ``__getitem__`` will be called with the
          name ``1`` during the traversal phase.  If the ``1`` object
          exists, it will become the :term:`context` of the request.
          :ref:`traversal_chapter` has more information about
          traversal.

          If the traversal path contains segment marker names which
          are not present in the ``pattern`` argument, a runtime error
          will occur.  The ``traverse`` pattern should not contain
          segment markers that do not exist in the ``pattern``
          argument.

          A similar combining of routing and traversal is available
          when a route is matched which contains a ``*traverse``
          remainder marker in its pattern (see
          :ref:`using_traverse_in_a_route_pattern`).  The ``traverse``
          argument to add_route allows you to associate route patterns
          with an arbitrary traversal path without using a a
          ``*traverse`` remainder marker; instead you can use other
          match information.

          Note that the ``traverse`` argument to ``add_route`` is
          ignored when attached to a route that has a ``*traverse``
          remainder marker in its pattern.

        pregenerator

           This option should be a callable object that implements the
           :class:`pyramid.interfaces.IRoutePregenerator`
           interface.  A :term:`pregenerator` is a callable called by
           the :mod:`pyramid.url.route_url` function to augment or
           replace the arguments it is passed when generating a URL
           for the route.  This is a feature not often used directly
           by applications, it is meant to be hooked by frameworks
           that use :app:`Pyramid` as a base.

        Predicate Arguments

        pattern

          The pattern of the route e.g. ``ideas/{idea}``.  This
          argument is required.  See :ref:`route_path_pattern_syntax`
          for information about the syntax of route patterns.  If the
          pattern doesn't match the current URL, route matching
          continues.

          .. note:: For backwards compatibility purposes (as of
             :app:`Pyramid` 1.0), a ``path`` keyword argument passed
             to this function will be used to represent the pattern
             value if the ``pattern`` argument is ``None``.  If both
             ``path`` and ``pattern`` are passed, ``pattern`` wins.
        
        xhr

          This value should be either ``True`` or ``False``.  If this
          value is specified and is ``True``, the :term:`request` must
          possess an ``HTTP_X_REQUESTED_WITH`` (aka
          ``X-Requested-With``) header for this route to match.  This
          is useful for detecting AJAX requests issued from jQuery,
          Prototype and other Javascript libraries.  If this predicate
          returns ``False``, route matching continues.

        request_method

          A string representing an HTTP method name, e.g. ``GET``,
          ``POST``, ``HEAD``, ``DELETE``, ``PUT``.  If this argument
          is not specified, this route will match if the request has
          *any* request method.  If this predicate returns ``False``,
          route matching continues.

        path_info

          This value represents a regular expression pattern that will
          be tested against the ``PATH_INFO`` WSGI environment
          variable.  If the regex matches, this predicate will return
          ``True``.  If this predicate returns ``False``, route
          matching continues.

        request_param

          This value can be any string.  A view declaration with this
          argument ensures that the associated route will only match
          when the request has a key in the ``request.params``
          dictionary (an HTTP ``GET`` or ``POST`` variable) that has a
          name which matches the supplied value.  If the value
          supplied as the argument has a ``=`` sign in it,
          e.g. ``request_params="foo=123"``, then the key
          (``foo``) must both exist in the ``request.params`` dictionary, and
          the value must match the right hand side of the expression (``123``)
          for the route to "match" the current request.  If this predicate
          returns ``False``, route matching continues.

        header

          This argument represents an HTTP header name or a header
          name/value pair.  If the argument contains a ``:`` (colon),
          it will be considered a name/value pair
          (e.g. ``User-Agent:Mozilla/.*`` or ``Host:localhost``).  If
          the value contains a colon, the value portion should be a
          regular expression.  If the value does not contain a colon,
          the entire value will be considered to be the header name
          (e.g. ``If-Modified-Since``).  If the value evaluates to a
          header name only without a value, the header specified by
          the name must be present in the request for this predicate
          to be true.  If the value evaluates to a header name/value
          pair, the header specified by the name must be present in
          the request *and* the regular expression specified as the
          value must match the header value.  Whether or not the value
          represents a header name or a header name/value pair, the
          case of the header name is not significant.  If this
          predicate returns ``False``, route matching continues.

        accept

          This value represents a match query for one or more
          mimetypes in the ``Accept`` HTTP request header.  If this
          value is specified, it must be in one of the following
          forms: a mimetype match token in the form ``text/plain``, a
          wildcard mimetype match token in the form ``text/*`` or a
          match-all wildcard mimetype match token in the form ``*/*``.
          If any of the forms matches the ``Accept`` header of the
          request, this predicate will be true.  If this predicate
          returns ``False``, route matching continues.

        custom_predicates

          This value should be a sequence of references to custom
          predicate callables.  Use custom predicates when no set of
          predefined predicates does what you need.  Custom predicates
          can be combined with predefined predicates as necessary.
          Each custom predicate callable should accept two arguments:
          ``info`` and ``request`` and should return either ``True``
          or ``False`` after doing arbitrary evaluation of the info
          and/or the request.  If all custom and non-custom predicate
          callables return ``True`` the associated route will be
          considered viable for a given request.  If any predicate
          callable returns ``False``, route matching continues.  Note
          that the value ``info`` passed to a custom route predicate
          is a dictionary containing matching information; see
          :ref:`custom_route_predicates` for more information about
          ``info``.

        View-Related Arguments

        view

          A Python object or :term:`dotted Python name` to the same
          object that will be used as a view callable when this route
          matches. e.g. ``mypackage.views.my_view``.

        view_context

          A class or an :term:`interface` or :term:`dotted Python
          name` to the same object which the :term:`context` of the
          view should match for the view named by the route to be
          used.  This argument is only useful if the ``view``
          attribute is used.  If this attribute is not specified, the
          default (``None``) will be used.

          If the ``view`` argument is not provided, this argument has
          no effect.

          This attribute can also be spelled as ``for_`` or ``view_for``.

        view_permission

          The permission name required to invoke the view associated
          with this route.  e.g. ``edit``. (see
          :ref:`using_security_with_urldispatch` for more information
          about permissions).

          If the ``view`` attribute is not provided, this argument has
          no effect.

          This argument can also be spelled as ``permission``.

        view_renderer

          This is either a single string term (e.g. ``json``) or a
          string implying a path or :term:`resource specification`
          (e.g. ``templates/views.pt``).  If the renderer value is a
          single term (does not contain a dot ``.``), the specified
          term will be used to look up a renderer implementation, and
          that renderer implementation will be used to construct a
          response from the view return value.  If the renderer term
          contains a dot (``.``), the specified term will be treated
          as a path, and the filename extension of the last element in
          the path will be used to look up the renderer
          implementation, which will be passed the full path.  The
          renderer implementation will be used to construct a response
          from the view return value.  See
          :ref:`views_which_use_a_renderer` for more information.

          If the ``view`` argument is not provided, this argument has
          no effect.

          This argument can also be spelled as ``renderer``.

        view_attr

          The view machinery defaults to using the ``__call__`` method
          of the view callable (or the function itself, if the view
          callable is a function) to obtain a response dictionary.
          The ``attr`` value allows you to vary the method attribute
          used to obtain the response.  For example, if your view was
          a class, and the class has a method named ``index`` and you
          wanted to use this method instead of the class' ``__call__``
          method to return the response, you'd say ``attr="index"`` in
          the view configuration for the view.  This is
          most useful when the view definition is a class.

          If the ``view`` argument is not provided, this argument has no
          effect.

        use_global_views

          When a request matches this route, and view lookup cannot
          find a view which has a ``route_name`` predicate argument
          that matches the route, try to fall back to using a view
          that otherwise matches the context, request, and view name
          (but which does not match the route_name predicate).

        """
        # these are route predicates; if they do not match, the next route
        # in the routelist will be tried
        ignored, predicates, ignored = _make_predicates(
            xhr=xhr,
            request_method=request_method,
            path_info=path_info,
            request_param=request_param,
            header=header,
            accept=accept,
            traverse=traverse,
            custom=custom_predicates
            )

        request_iface = self.registry.queryUtility(IRouteRequest, name=name)
        if request_iface is None:
            bases = use_global_views and (IRequest,) or ()
            request_iface = route_request_iface(name, bases)
            self.registry.registerUtility(
                request_iface, IRouteRequest, name=name)
            deferred_views = getattr(self.registry, 'deferred_route_views', {})
            view_info = deferred_views.pop(name, ())
            for info in view_info:
                self.add_view(**info)

        if view:
            if view_context is None:
                view_context = view_for
                if view_context is None:
                    view_context = for_
            view_permission = view_permission or permission
            view_renderer = view_renderer or renderer
            self.add_view(
                permission=view_permission,
                context=view_context,
                view=view,
                name='',
                route_name=name,
                renderer=view_renderer,
                attr=view_attr,
                _info=_info,
                )

        mapper = self.get_routes_mapper()

        factory = self.maybe_dotted(factory)
        if pattern is None:
            pattern = path
        if pattern is None:
            raise ConfigurationError('"pattern" argument may not be None')

        return mapper.connect(name, pattern, factory, predicates=predicates,
                              pregenerator=pregenerator)

    def get_routes_mapper(self):
        """ Return the :term:`routes mapper` object associated with
        this configurator's :term:`registry`."""
        mapper = self.registry.queryUtility(IRoutesMapper)
        if mapper is None:
            mapper = RoutesMapper()
            self.registry.registerUtility(mapper, IRoutesMapper)
        return mapper

    def scan(self, package=None, categories=None, _info=u''):
        """ Scan a Python package and any of its subpackages for
        objects marked with :term:`configuration decoration` such as
        :class:`pyramid.view.view_config`.  Any decorated object found
        will influence the current configuration state.

        The ``package`` argument should be a Python :term:`package` or
        module object (or a :term:`dotted Python name` which refers to
        such a package or module).  If ``package`` is ``None``, the
        package of the *caller* is used.

        The ``categories`` argument, if provided, should be the
        :term:`Venusian` 'scan categories' to use during scanning.
        Providing this argument is not often necessary; specifying
        scan categories is an extremely advanced usage.

        By default, ``categories`` is ``None`` which will execute
        *all* Venusian decorator callbacks including
        :app:`Pyramid`-related decorators such as
        :class:`pyramid.view.view_config`.  If this is not desirable
        because the codebase has other Venusian-using decorators that
        aren't meant to be invoked during a particular scan, use
        ``('pyramid',)`` as a ``categories`` value to limit the execution
        of decorator callbacks to only those registered by
        :app:`Pyramid` itself.  Or pass a sequence of Venusian scan
        categories as necessary (e.g. ``('pyramid', 'myframework')``) to
        limit the decorators called to the set of categories required.
        """
        package = self.maybe_dotted(package)
        if package is None: # pragma: no cover
            package = caller_package()

        scanner = self.venusian.Scanner(config=self)
        scanner.scan(package, categories=categories)

    def add_renderer(self, name, factory, _info=u''):
        """
        Add a :app:`Pyramid` :term:`renderer` factory to the
        current configuration state.

        The ``name`` argument is the renderer name.  Use ``None`` to
        represent the default renderer (a renderer which will be used for all
        views unless they name another renderer specifically).

        The ``factory`` argument is Python reference to an
        implementation of a :term:`renderer` factory or a
        :term:`dotted Python name` to same.

        Note that this function must be called *before* any
        ``add_view`` invocation that names the renderer name as an
        argument.  As a result, it's usually a better idea to pass
        globally used renderers into the ``Configurator`` constructor
        in the sequence of renderers passed as ``renderer`` than it is
        to use this method.
        """
        factory = self.maybe_dotted(factory)
        # if name is None or the empty string, we're trying to register
        # a default renderer, but registerUtility is too dumb to accept None
        # as a name
        if not name: 
            name = ''
        self.registry.registerUtility(
            factory, IRendererFactory, name=name, info=_info)

    def override_resource(self, to_override, override_with,
                          _info=u'', _override=None,):
        """ Add a :app:`Pyramid` resource override to the current
        configuration state.

        ``to_override`` is a :term:`resource specification` to the
        resource being overridden.

        ``override_with`` is a :term:`resource specification` to the
        resource that is performing the override.

        See :ref:`resources_chapter` for more
        information about resource overrides."""
        if to_override == override_with:
            raise ConfigurationError('You cannot override a resource with '
                                     'itself')

        package = to_override
        path = ''
        if ':' in to_override:
            package, path = to_override.split(':', 1)

        override_package = override_with
        override_prefix = ''
        if ':' in override_with:
            override_package, override_prefix = override_with.split(':', 1)

        if path and path.endswith('/'):
            if override_prefix and (not override_prefix.endswith('/')):
                raise ConfigurationError(
                    'A directory cannot be overridden with a file (put a '
                    'slash at the end of override_with if necessary)')

        if override_prefix and override_prefix.endswith('/'):
            if path and (not path.endswith('/')):
                raise ConfigurationError(
                    'A file cannot be overridden with a directory (put a '
                    'slash at the end of to_override if necessary)')

        __import__(package)
        __import__(override_package)
        package = sys.modules[package]
        override_package = sys.modules[override_package]

        override = _override or self._override # test jig
        override(package, path, override_package, override_prefix,
                 _info=_info)

    def set_forbidden_view(self, view=None, attr=None, renderer=None,
                           wrapper=None, _info=u''):
        """ Add a default forbidden view to the current configuration
        state.

        .. warning:: This method has been deprecated in :app:`Pyramid`
           1.0.  *Do not use it for new development; it should only be
           used to support older code bases which depend upon it.* See
           :ref:`changing_the_forbidden_view` to see how a forbidden
           view should be registered in new projects.

        The ``view`` argument should be a :term:`view callable` or a
        :term:`dotted Python name` which refers to a view callable.

        The ``attr`` argument should be the attribute of the view
        callable used to retrieve the response (see the ``add_view``
        method's ``attr`` argument for a description).

        The ``renderer`` argument should be the name of (or path to) a
        :term:`renderer` used to generate a response for this view
        (see the
        :meth:`pyramid.configuration.Configurator.add_view`
        method's ``renderer`` argument for information about how a
        configurator relates to a renderer).

        The ``wrapper`` argument should be the name of another view
        which will wrap this view when rendered (see the ``add_view``
        method's ``wrapper`` argument for a description)."""
        if renderer is not None and not isinstance(renderer, dict):
            renderer = {'name':renderer, 'package':self.package}
        view = self._derive_view(view, attr=attr, renderer=renderer)
        def bwcompat_view(context, request):
            context = getattr(request, 'context', None)
            return view(context, request)
        return self.add_view(bwcompat_view, context=Forbidden,
                             wrapper=wrapper, _info=_info)

    def set_notfound_view(self, view=None, attr=None, renderer=None,
                          wrapper=None, _info=u''):
        """ Add a default not found view to the current configuration
        state.

        .. warning:: This method has been deprecated in
           :app:`Pyramid` 1.0.  *Do not use it for new development;
           it should only be used to support older code bases which
           depend upon it.* See :ref:`changing_the_notfound_view` to
           see how a not found view should be registered in new
           projects.

        The ``view`` argument should be a :term:`view callable` or a
        :term:`dotted Python name` which refers to a view callable.

        The ``attr`` argument should be the attribute of the view
        callable used to retrieve the response (see the ``add_view``
        method's ``attr`` argument for a description).

        The ``renderer`` argument should be the name of (or path to) a
        :term:`renderer` used to generate a response for this view
        (see the
        :meth:`pyramid.configuration.Configurator.add_view`
        method's ``renderer`` argument for information about how a
        configurator relates to a renderer).

        The ``wrapper`` argument should be the name of another view
        which will wrap this view when rendered (see the ``add_view``
        method's ``wrapper`` argument for a description).
        """
        if renderer is not None and not isinstance(renderer, dict):
            renderer = {'name':renderer, 'package':self.package}
        view = self._derive_view(view, attr=attr, renderer=renderer)
        def bwcompat_view(context, request):
            context = getattr(request, 'context', None)
            return view(context, request)
        return self.add_view(bwcompat_view, context=NotFound,
                             wrapper=wrapper, _info=_info)

    def set_request_factory(self, factory):
        """ The object passed as ``factory`` should be an object (or a
        :term:`dotted Python name` which refers to an object) which
        will be used by the :app:`Pyramid` router to create all
        request objects.  This factory object must have the same
        methods and attributes as the
        :class:`pyramid.request.Request` class (particularly
        ``__call__``, and ``blank``).

        .. note:: Using the :meth:``request_factory`` argument to the
           :class:`pyramid.configuration.Configurator` constructor
           can be used to achieve the same purpose.
        """
        factory = self.maybe_dotted(factory)
        self.registry.registerUtility(factory, IRequestFactory)

    def set_renderer_globals_factory(self, factory):
        """ The object passed as ``factory`` should be an callable (or
        a :term:`dotted Python name` which refers to an callable) that
        will be used by the :app:`Pyramid` rendering machinery as a
        renderers global factory (see :ref:`adding_renderer_globals`).

        The ``factory`` callable must accept a single argument named
        ``system`` (which will be a dictionary) and it must return a
        dictionary.  When an application uses a renderer, the
        factory's return dictionary will be merged into the ``system``
        dictionary, and therefore will be made available to the code
        which uses the renderer.

        .. note:: Using the :meth:`renderer_globals_factory`
           argument to the
           :class:`pyramid.configuration.Configurator` constructor
           can be used to achieve the same purpose.
        """
        factory = self.maybe_dotted(factory)
        self.registry.registerUtility(factory, IRendererGlobalsFactory)

    def set_locale_negotiator(self, negotiator):
        """
        Set the :term:`locale negotiator` for this application.  The
        :term:`locale negotiator` is a callable which accepts a
        :term:`request` object and which returns a :term:`locale
        name`.  The ``negotiator`` argument should be the locale
        negotiator implementation or a :term:`dotted Python name`
        which refers to such an implementation.

        Later calls to this method override earlier calls; there can
        be only one locale negotiator active at a time within an
        application.  See :ref:`activating_translation` for more
        information.

        .. note:: Using the ``locale_negotiator`` argument to the
           :class:`pyramid.configuration.Configurator` constructor
           can be used to achieve the same purpose.
        """
        negotiator = self.maybe_dotted(negotiator)
        self.registry.registerUtility(negotiator, ILocaleNegotiator)

    def set_default_permission(self, permission):
        """
        Set the default permission to be used by all subsequent
        :term:`view configuration` registrations.  ``permission``
        should be a :term:`permission` string to be used as the
        default permission.  An example of a permission
        string:``'view'``.  Adding a default permission makes it
        unnecessary to protect each view configuration with an
        explicit permission, unless your application policy requires
        some exception for a particular view.

        If a default permission is *not* set, views represented by
        view configuration registrations which do not explicitly
        declare a permission will be executable by entirely anonymous
        users (any authorization policy is ignored).

        Later calls to this method override earlier calls; there can
        be only one default permission active at a time within an
        application.

        See also :ref:`setting_a_default_permission`.

        .. note:: Using the ``default_permission`` argument to the
           :class:`pyramid.configuration.Configurator` constructor
           can be used to achieve the same purpose.
        """
        self.registry.registerUtility(permission, IDefaultPermission)

    def set_session_factory(self, session_factory):
        """
        Configure the application with a :term:`session factory`.  If
        this method is called, the ``session_factory`` argument must
        be a session factory callable.
        """
        self.registry.registerUtility(session_factory, ISessionFactory)

    def add_translation_dirs(self, *specs):
        """ Add one or more :term:`translation directory` paths to the
        current configuration state.  The ``specs`` argument is a
        sequence that may contain absolute directory paths
        (e.g. ``/usr/share/locale``) or :term:`resource specification`
        names naming a directory path (e.g. ``some.package:locale``)
        or a combination of the two.

        Example:

        .. code-block:: python

           add_translations_dirs('/usr/share/locale', 'some.package:locale')

        """
        for spec in specs:

            package_name, filename = self._split_spec(spec)
            if package_name is None: # absolute filename
                directory = filename
            else:
                __import__(package_name)
                package = sys.modules[package_name]
                directory = os.path.join(package_path(package), filename)

            if not os.path.isdir(os.path.realpath(directory)):
                raise ConfigurationError('"%s" is not a directory' % directory)

            tdirs = self.registry.queryUtility(ITranslationDirectories)
            if tdirs is None:
                tdirs = []
                self.registry.registerUtility(tdirs, ITranslationDirectories)

            tdirs.insert(0, directory)

        if specs:

            # We actually only need an IChameleonTranslate function
            # utility to be registered zero or one times.  We register the
            # same function once for each added translation directory,
            # which does too much work, but has the same effect.

            def translator(msg):
                request = get_current_request()
                localizer = get_localizer(request)
                return localizer.translate(msg)

            ctranslate = ChameleonTranslate(translator)
            self.registry.registerUtility(ctranslate, IChameleonTranslate)

    def add_static_view(self, name, path, **kw):
        """ Add a view used to render static resources such as images
        and CSS files.

        The ``name`` argument is a string representing :term:`view
        name` of the view which is registered.  It may alternately be
        a *url prefix*.

        The ``path`` argument is the path on disk where the static
        files reside.  This can be an absolute path, a
        package-relative path, or a :term:`resource specification`.

        The ``cache_max_age`` keyword argument is input to set the
        ``Expires`` and ``Cache-Control`` headers for static resources
        served.  Note that this argument has no effect when the
        ``name`` is a *url prefix*.  By default, this argument is
        ``None``, meaning that no particular Expires or Cache-Control
        headers are set in the response.

        The ``permission`` keyword argument is used to specify the
        :term:`permission` required by a user to execute the static
        view.  By default, it is the string
        ``__no_permission_required__``.  The
        ``__no_permission_required__`` string is a special sentinel
        which indicates that, even if a :term:`default permission`
        exists for the current application, the static view should be
        renderered to completely anonymous users.  This default value
        is permissive because, in most web apps, static resources
        seldom need protection from viewing.

        *Usage*

        The ``add_static_view`` function is typically used in
        conjunction with the :func:`pyramid.url.static_url`
        function.  ``add_static_view`` adds a view which renders a
        static resource when some URL is visited;
        :func:`pyramid.url.static_url` generates a URL to that
        resource.

        The ``name`` argument to ``add_static_view`` is usually a
        :term:`view name`.  When this is the case, the
        :func:`pyramid.url.static_url` API will generate a URL
        which points to a Pyramid view, which will serve up a set of
        resources that live in the package itself. For example:

        .. code-block:: python

           add_static_view('images', 'mypackage:images/')

        Code that registers such a view can generate URLs to the view
        via :func:`pyramid.url.static_url`:

        .. code-block:: python

           static_url('mypackage:images/logo.png', request)

        When ``add_static_view`` is called with a ``name`` argument
        that represents a simple view name, as it is above, subsequent
        calls to :func:`pyramid.url.static_url` with paths that
        start with the ``path`` argument passed to ``add_static_view``
        will generate a URL something like ``http://<Pyramid app
        URL>/images/logo.png``, which will cause the ``logo.png`` file
        in the ``images`` subdirectory of the ``mypackage`` package to
        be served.

        ``add_static_view`` can alternately be used with a ``name``
        argument which is a *URL*, causing static resources to be
        served from an external webserver.  This happens when the
        ``name`` argument is a URL (detected as any string with a
        slash in it).  In this mode, the ``name`` is used as the URL
        prefix when generating a URL using
        :func:`pyramid.url.static_url`.  For example, if
        ``add_static_view`` is called like so:

        .. code-block:: python

           add_static_view('http://example.com/images', 'mypackage:images/')

        Subsequently, the URLs generated by
        :func:`pyramid.url.static_url` for that static view will be
        prefixed with ``http://example.com/images``:

        .. code-block:: python

           static_url('mypackage:images/logo.png', request)

        When ``add_static_view`` is called with a ``name`` argument
        that is the URL prefix ``http://example.com/images``,
        subsequent calls to :func:`pyramid.url.static_url` with
        paths that start with the ``path`` argument passed to
        ``add_static_view`` will generate a URL something like
        ``http://example.com/logo.png``.  The external webserver
        listening on ``example.com`` must be itself configured to
        respond properly to such a request.

        See :ref:`static_resources_section` for more information.
        """
        spec = self._make_spec(path)
        info = self.registry.queryUtility(IStaticURLInfo)
        if info is None:
            info = StaticURLInfo(self)
            self.registry.registerUtility(info, IStaticURLInfo)

        info.add(name, spec, **kw)

    # testing API
    def testing_securitypolicy(self, userid=None, groupids=(),
                               permissive=True):
        """Unit/integration testing helper: Registers a pair of faux
        :app:`Pyramid` security policies: a :term:`authentication
        policy` and a :term:`authorization policy`.

        The behavior of the registered :term:`authorization policy`
        depends on the ``permissive`` argument.  If ``permissive`` is
        true, a permissive :term:`authorization policy` is registered;
        this policy allows all access.  If ``permissive`` is false, a
        nonpermissive :term:`authorization policy` is registered; this
        policy denies all access.

        The behavior of the registered :term:`authentication policy`
        depends on the values provided for the ``userid`` and
        ``groupids`` argument.  The authentication policy will return
        the userid identifier implied by the ``userid`` argument and
        the group ids implied by the ``groupids`` argument when the
        :func:`pyramid.security.authenticated_userid` or
        :func:`pyramid.security.effective_principals` APIs are
        used.

        This function is most useful when testing code that uses
        the APIs named :func:`pyramid.security.has_permission`,
        :func:`pyramid.security.authenticated_userid`,
        :func:`pyramid.security.effective_principals`, and
        :func:`pyramid.security.principals_allowed_by_permission`.
        """
        from pyramid.testing import DummySecurityPolicy
        policy = DummySecurityPolicy(userid, groupids, permissive)
        self.registry.registerUtility(policy, IAuthorizationPolicy)
        self.registry.registerUtility(policy, IAuthenticationPolicy)

    def testing_models(self, models):
        """Unit/integration testing helper: registers a dictionary of
        :term:`model` objects that can be resolved via the
        :func:`pyramid.traversal.find_model` API.

        The :func:`pyramid.traversal.find_model` API is called with
        a path as one of its arguments.  If the dictionary you
        register when calling this method contains that path as a
        string key (e.g. ``/foo/bar`` or ``foo/bar``), the
        corresponding value will be returned to ``find_model`` (and
        thus to your code) when
        :func:`pyramid.traversal.find_model` is called with an
        equivalent path string or tuple.
        """
        class DummyTraverserFactory:
            def __init__(self, context):
                self.context = context

            def __call__(self, request):
                path = request['PATH_INFO']
                ob = models[path]
                traversed = traversal_path(path)
                return {'context':ob, 'view_name':'','subpath':(),
                        'traversed':traversed, 'virtual_root':ob,
                        'virtual_root_path':(), 'root':ob}
        self.registry.registerAdapter(DummyTraverserFactory, (Interface,),
                                      ITraverser)
        return models

    def testing_add_subscriber(self, event_iface=None):
        """Unit/integration testing helper: Registers a
        :term:`subscriber` which listens for events of the type
        ``event_iface``.  This method returns a list object which is
        appended to by the subscriber whenever an event is captured.

        When an event is dispatched that matches the value implied by
        the ``event_iface`` argument, that event will be appended to
        the list.  You can then compare the values in the list to
        expected event notifications.  This method is useful when
        testing code that wants to call
        :meth:`pyramid.registry.Registry.notify`,
        :func:`zope.component.event.dispatch` or
        :func:`zope.component.event.objectEventNotify`.

        The default value of ``event_iface`` (``None``) implies a
        subscriber registered for *any* kind of event.
        """
        event_iface = self.maybe_dotted(event_iface)
        L = []
        def subscriber(*event):
            L.extend(event)
        self.add_subscriber(subscriber, event_iface)
        return L

    def testing_add_renderer(self, path, renderer=None):
        """Unit/integration testing helper: register a renderer at
        ``path`` (usually a relative filename ala ``templates/foo.pt``
        or a resource specification) and return the renderer object.
        If the ``renderer`` argument is None, a 'dummy' renderer will
        be used.  This function is useful when testing code that calls
        the :func:`pyramid.renderers.render` function or
        :func:`pyramid.renderers.render_to_response` function or
        any other ``render_*`` or ``get_*`` API of the
        :mod:`pyramid.renderers` module.

        Note that calling this method for with a ``path`` argument
        representing a renderer factory type (e.g. for ``foo.pt``
        usually implies the ``chameleon_zpt`` renderer factory)
        clobbers any existing renderer factory registered for that
        type.

        .. note:: This method is also available under the alias
           ``testing_add_template`` (an older name for it).

        """
        from pyramid.testing import DummyRendererFactory
        helper = RendererHelper(name=path, registry=self.registry)
        factory = self.registry.queryUtility(IRendererFactory, name=helper.type)
        if not isinstance(factory, DummyRendererFactory):
            factory = DummyRendererFactory(helper.type, factory)
            self.registry.registerUtility(factory, IRendererFactory,
                                          name=helper.type)

        from pyramid.testing import DummyTemplateRenderer
        if renderer is None:
            renderer = DummyTemplateRenderer()
        factory.add(path, renderer)
        return renderer

    testing_add_template = testing_add_renderer

def _make_predicates(xhr=None, request_method=None, path_info=None,
                     request_param=None, header=None, accept=None,
                     containment=None, request_type=None,
                     traverse=None, custom=()):

    # PREDICATES
    # ----------
    #
    # Given an argument list, a predicate list is computed.
    # Predicates are added to a predicate list in (presumed)
    # computation expense order.  All predicates associated with a
    # view or route must evaluate true for the view or route to
    # "match" during a request.  Elsewhere in the code, we evaluate
    # predicates using a generator expression.  The fastest predicate
    # should be evaluated first, then the next fastest, and so on, as
    # if one returns false, the remainder of the predicates won't need
    # to be evaluated.
    #
    # While we compute predicates, we also compute a predicate hash
    # (aka phash) that can be used by a caller to identify identical
    # predicate lists.
    #
    # ORDERING
    # --------
    #
    # A "order" is computed for the predicate list.  An order is
    # a scoring.
    #
    # Each predicate is associated with a weight value, which is a
    # multiple of 2.  The weight of a predicate symbolizes the
    # relative potential "importance" of the predicate to all other
    # predicates.  A larger weight indicates greater importance.
    #
    # All weights for a given predicate list are bitwise ORed together
    # to create a "score"; this score is then subtracted from
    # MAX_ORDER and divided by an integer representing the number of
    # predicates+1 to determine the order.
    #
    # The order represents the ordering in which a "multiview" ( a
    # collection of views that share the same context/request/name
    # triad but differ in other ways via predicates) will attempt to
    # call its set of views.  Views with lower orders will be tried
    # first.  The intent is to a) ensure that views with more
    # predicates are always evaluated before views with fewer
    # predicates and b) to ensure a stable call ordering of views that
    # share the same number of predicates.  Views which do not have
    # any predicates get an order of MAX_ORDER, meaning that they will
    # be tried very last.

    predicates = []
    weights = []
    h = md5()

    if xhr:
        def xhr_predicate(context, request):
            return request.is_xhr
        weights.append(1 << 1)
        predicates.append(xhr_predicate)
        h.update('xhr:%r' % bool(xhr))

    if request_method is not None:
        def request_method_predicate(context, request):
            return request.method == request_method
        weights.append(1 << 2)
        predicates.append(request_method_predicate)
        h.update('request_method:%r' % request_method)

    if path_info is not None:
        try:
            path_info_val = re.compile(path_info)
        except re.error, why:
            raise ConfigurationError(why[0])
        def path_info_predicate(context, request):
            return path_info_val.match(request.path_info) is not None
        weights.append(1 << 3)
        predicates.append(path_info_predicate)
        h.update('path_info:%r' % path_info)

    if request_param is not None:
        request_param_val = None
        if '=' in request_param:
            request_param, request_param_val = request_param.split('=', 1)
        def request_param_predicate(context, request):
            if request_param_val is None:
                return request_param in request.params
            return request.params.get(request_param) == request_param_val
        weights.append(1 << 4)
        predicates.append(request_param_predicate)
        h.update('request_param:%r=%r' % (request_param, request_param_val))

    if header is not None:
        header_name = header
        header_val = None
        if ':' in header:
            header_name, header_val = header.split(':', 1)
            try:
                header_val = re.compile(header_val)
            except re.error, why:
                raise ConfigurationError(why[0])
        def header_predicate(context, request):
            if header_val is None:
                return header_name in request.headers
            val = request.headers.get(header_name)
            if val is None:
                return False
            return header_val.match(val) is not None
        weights.append(1 << 5)
        predicates.append(header_predicate)
        h.update('header:%r=%r' % (header_name, header_val))

    if accept is not None:
        def accept_predicate(context, request):
            return accept in request.accept
        weights.append(1 << 6)
        predicates.append(accept_predicate)
        h.update('accept:%r' % accept)

    if containment is not None:
        def containment_predicate(context, request):
            return find_interface(context, containment) is not None
        weights.append(1 << 7)
        predicates.append(containment_predicate)
        h.update('containment:%r' % hash(containment))

    if request_type is not None:
        def request_type_predicate(context, request):
            return request_type.providedBy(request)
        weights.append(1 << 8)
        predicates.append(request_type_predicate)
        h.update('request_type:%r' % hash(request_type))

    if traverse is not None:
        # ``traverse`` can only be used as a *route* "predicate"; it
        # adds 'traverse' to the matchdict if it's specified in the
        # routing args.  This causes the ModelGraphTraverser to use
        # the resolved traverse pattern as the traversal path.
        from pyramid.urldispatch import _compile_route
        _, tgenerate = _compile_route(traverse)
        def traverse_predicate(context, request):
            if 'traverse' in context:
                return True
            m = context['match']
            tvalue = tgenerate(m)
            m['traverse'] = traversal_path(tvalue)
            return True
        # This isn't actually a predicate, it's just a infodict
        # modifier that injects ``traverse`` into the matchdict.  As a
        # result, the ``traverse_predicate`` function above always
        # returns True, and we don't need to update the hash or attach
        # a weight to it
        predicates.append(traverse_predicate)

    if custom:
        for num, predicate in enumerate(custom):
            predicates.append(predicate)
            # using hash() here rather than id() is intentional: we
            # want to allow custom predicates that are part of
            # frameworks to be able to define custom __hash__
            # functions for custom predicates, so that the hash output
            # of predicate instances which are "logically the same"
            # may compare equal.
            h.update('custom%s:%r' % (num, hash(predicate)))
        weights.append(1 << 10)

    score = 0
    for bit in weights:
        score = score | bit
    order = (MAX_ORDER - score) / (len(predicates) + 1)
    phash = h.hexdigest()
    return order, predicates, phash

class MultiView(object):
    implements(IMultiView)

    def __init__(self, name):
        self.name = name
        self.media_views = {}
        self.views = []
        self.accepts = []

    def add(self, view, order, accept=None, phash=None):
        if phash is not None:
            for i, (s, v, h) in enumerate(list(self.views)):
                if phash == h:
                    self.views[i] = (order, view, phash)
                    return

        if accept is None or '*' in accept:
            self.views.append((order, view, phash))
            self.views.sort()
        else:
            subset = self.media_views.setdefault(accept, [])
            subset.append((order, view, phash))
            subset.sort()
            accepts = set(self.accepts)
            accepts.add(accept)
            self.accepts = list(accepts) # dedupe

    def get_views(self, request):
        if self.accepts and hasattr(request, 'accept'):
            accepts = self.accepts[:]
            views = []
            while accepts:
                match = request.accept.best_match(accepts)
                if match is None:
                    break
                subset = self.media_views[match]
                views.extend(subset)
                accepts.remove(match)
            views.extend(self.views)
            return views
        return self.views

    def match(self, context, request):
        for order, view, phash in self.get_views(request):
            if not hasattr(view, '__predicated__'):
                return view
            if view.__predicated__(context, request):
                return view
        raise PredicateMismatch(self.name)

    def __permitted__(self, context, request):
        view = self.match(context, request)
        if hasattr(view, '__permitted__'):
            return view.__permitted__(context, request)
        return True

    def __call_permissive__(self, context, request):
        view = self.match(context, request)
        view = getattr(view, '__call_permissive__', view)
        return view(context, request)

    def __call__(self, context, request):
        for order, view, phash in self.get_views(request):
            try:
                return view(context, request)
            except PredicateMismatch:
                continue
        raise PredicateMismatch(self.name)

def decorate_view(wrapped_view, original_view):
    if wrapped_view is original_view:
        return False
    wrapped_view.__module__ = original_view.__module__
    wrapped_view.__doc__ = original_view.__doc__
    try:
        wrapped_view.__name__ = original_view.__name__
    except AttributeError:
        wrapped_view.__name__ = repr(original_view)
    try:
        wrapped_view.__permitted__ = original_view.__permitted__
    except AttributeError:
        pass
    try:
        wrapped_view.__call_permissive__ = original_view.__call_permissive__
    except AttributeError:
        pass
    try:
        wrapped_view.__predicated__ = original_view.__predicated__
    except AttributeError:
        pass
    try:
        wrapped_view.__accept__ = original_view.__accept__
    except AttributeError:
        pass
    try:
        wrapped_view.__order__ = original_view.__order__
    except AttributeError:
        pass
    return True

def requestonly(class_or_callable, attr=None):
    """ Return true of the class or callable accepts only a request argument,
    as opposed to something that accepts context, request """
    if attr is None:
        attr = '__call__'
    if inspect.isfunction(class_or_callable):
        fn = class_or_callable
    elif inspect.isclass(class_or_callable):
        try:
            fn = class_or_callable.__init__
        except AttributeError:
            return False
    else:
        try:
            fn = getattr(class_or_callable, attr)
        except AttributeError:
            return False

    try:
        argspec = inspect.getargspec(fn)
    except TypeError:
        return False

    args = argspec[0]
    defaults = argspec[3]

    if hasattr(fn, 'im_func'):
        # it's an instance method
        if not args:
            return False
        args = args[1:]
    if not args:
        return False

    if len(args) == 1:
        return True

    elif args[0] == 'request':
        if len(args) - len(defaults) == 1:
            return True

    return False

def is_response(ob):
    if ( hasattr(ob, 'app_iter') and hasattr(ob, 'headerlist') and
         hasattr(ob, 'status') ):
        return True
    return False

def _map_view(view, registry, attr=None, renderer=None):
    wrapped_view = view

    helper = None

    if renderer is not None:
        helper = RendererHelper(renderer['name'],
                                package=renderer['package'],
                                registry=registry)

    if inspect.isclass(view):
        # If the object we've located is a class, turn it into a
        # function that operates like a Zope view (when it's invoked,
        # construct an instance using 'context' and 'request' as
        # position arguments, then immediately invoke the __call__
        # method of the instance with no arguments; __call__ should
        # return an IResponse).
        if requestonly(view, attr):
            # its __init__ accepts only a single request argument,
            # instead of both context and request
            def _class_requestonly_view(context, request):
                inst = view(request)
                if attr is None:
                    response = inst()
                else:
                    response = getattr(inst, attr)()
                if helper is not None:
                    if not is_response(response):
                        system = {
                            'view':inst,
                            'renderer_name':renderer['name'], # b/c
                            'renderer_info':renderer,
                            'context':context,
                            'request':request
                            }
                        response = helper.render_to_response(response, system,
                                                             request=request)
                return response
            wrapped_view = _class_requestonly_view
        else:
            # its __init__ accepts both context and request
            def _class_view(context, request):
                inst = view(context, request)
                if attr is None:
                    response = inst()
                else:
                    response = getattr(inst, attr)()
                if helper is not None:
                    if not is_response(response):
                        system = {'view':inst,
                                  'renderer_name':renderer['name'], # b/c
                                  'renderer_info':renderer,
                                  'context':context,
                                  'request':request
                                  }
                        response = helper.render_to_response(response, system,
                                                             request=request)
                return response
            wrapped_view = _class_view

    elif requestonly(view, attr):
        # its __call__ accepts only a single request argument,
        # instead of both context and request
        def _requestonly_view(context, request):
            if attr is None:
                response = view(request)
            else:
                response = getattr(view, attr)(request)

            if helper is not None:
                if not is_response(response):
                    system = {
                        'view':view,
                        'renderer_name':renderer['name'],
                        'renderer_info':renderer,
                        'context':context,
                        'request':request
                        }
                    response = helper.render_to_response(response, system,
                                                         request=request)
            return response
        wrapped_view = _requestonly_view

    elif attr:
        def _attr_view(context, request):
            response = getattr(view, attr)(context, request)
            if helper is not None:
                if not is_response(response):
                    system = {
                        'view':view,
                        'renderer_name':renderer['name'],
                        'renderer_info':renderer,
                        'context':context,
                        'request':request
                        }
                    response = helper.render_to_response(response, system,
                                                         request=request)
            return response
        wrapped_view = _attr_view

    elif helper is not None:
        def _rendered_view(context, request):
            response = view(context, request)
            if not is_response(response):
                system = {
                    'view':view,
                    'renderer_name':renderer['name'], # b/c
                    'renderer_info':renderer,
                    'context':context,
                    'request':request
                    }
                response = helper.render_to_response(response, system,
                                                     request=request)
            return response
        wrapped_view = _rendered_view

    decorate_view(wrapped_view, view)
    return wrapped_view

def _owrap_view(view, viewname, wrapper_viewname):
    if not wrapper_viewname:
        return view
    def _owrapped_view(context, request):
        response = view(context, request)
        request.wrapped_response = response
        request.wrapped_body = response.body
        request.wrapped_view = view
        wrapped_response = render_view_to_response(context, request,
                                                   wrapper_viewname)
        if wrapped_response is None:
            raise ValueError(
                'No wrapper view named %r found when executing view '
                'named %r' % (wrapper_viewname, viewname))
        return wrapped_response
    decorate_view(_owrapped_view, view)
    return _owrapped_view

def _predicate_wrap(view, predicates):
    if not predicates:
        return view
    def predicate_wrapper(context, request):
        if all((predicate(context, request) for predicate in predicates)):
            return view(context, request)
        raise PredicateMismatch('predicate mismatch for view %s' % view)
    def checker(context, request):
        return all((predicate(context, request) for predicate in
                    predicates))
    predicate_wrapper.__predicated__ = checker
    decorate_view(predicate_wrapper, view)
    return predicate_wrapper

def _secure_view(view, permission, authn_policy, authz_policy):
    if permission == '__no_permission_required__':
        # allow views registered within configurations that have a
        # default permission to explicitly override the default
        # permission, replacing it with no permission at all
        permission = None

    wrapped_view = view
    if authn_policy and authz_policy and (permission is not None):
        def _secured_view(context, request):
            principals = authn_policy.effective_principals(request)
            if authz_policy.permits(context, principals, permission):
                return view(context, request)
            msg = getattr(request, 'authdebug_message',
                          'Unauthorized: %s failed permission check' % view)
            raise Forbidden(msg)
        _secured_view.__call_permissive__ = view
        def _permitted(context, request):
            principals = authn_policy.effective_principals(request)
            return authz_policy.permits(context, principals, permission)
        _secured_view.__permitted__ = _permitted
        wrapped_view = _secured_view
        decorate_view(wrapped_view, view)

    return wrapped_view

def _authdebug_view(view, permission, authn_policy, authz_policy, settings,
                    logger):
    wrapped_view = view
    if settings and settings.get('debug_authorization', False):
        def _authdebug_view(context, request):
            view_name = getattr(request, 'view_name', None)

            if authn_policy and authz_policy:
                if permission is None:
                    msg = 'Allowed (no permission registered)'
                else:
                    principals = authn_policy.effective_principals(request)
                    msg = str(authz_policy.permits(context, principals,
                                                   permission))
            else:
                msg = 'Allowed (no authorization policy in use)'

            view_name = getattr(request, 'view_name', None)
            url = getattr(request, 'url', None)
            msg = ('debug_authorization of url %s (view name %r against '
                   'context %r): %s' % (url, view_name, context, msg))
            logger and logger.debug(msg)
            if request is not None:
                request.authdebug_message = msg
            return view(context, request)

        wrapped_view = _authdebug_view
        decorate_view(wrapped_view, view)

    return wrapped_view

def _attr_wrap(view, accept, order, phash):
    # this is a little silly but we don't want to decorate the original
    # function with attributes that indicate accept, order, and phash,
    # so we use a wrapper
    if (accept is None) and (order == MAX_ORDER) and (phash == DEFAULT_PHASH):
        return view # defaults
    def attr_view(context, request):
        return view(context, request)
    attr_view.__accept__ = accept
    attr_view.__order__ = order
    attr_view.__phash__ = phash
    decorate_view(attr_view, view)
    return attr_view

def isexception(o):
    if IInterface.providedBy(o):
        if IException.isEqualOrExtendedBy(o):
            return True
    return (
        isinstance(o, Exception) or
        (inspect.isclass(o) and (issubclass(o, Exception)))
        )

# note that ``options`` is a b/w compat alias for ``settings`` and
# ``Configurator`` is a testing dep inj
def make_app(root_factory, package=None, filename='configure.zcml',
             settings=None, options=None, Configurator=Configurator):
    """ Return a Router object, representing a fully configured
    :app:`Pyramid` WSGI application.

    .. warning:: Use of this function is deprecated as of
       :app:`Pyramid` 1.0.  You should instead use a
       :class:`pyramid.configuration.Configurator` instance to
       perform startup configuration as shown in
       :ref:`configuration_narr`.

    ``root_factory`` must be a callable that accepts a :term:`request`
    object and which returns a traversal root object.  The traversal
    root returned by the root factory is the *default* traversal root;
    it can be overridden on a per-view basis.  ``root_factory`` may be
    ``None``, in which case a 'default default' traversal root is
    used.

    ``package`` is a Python :term:`package` or module representing the
    application's package.  It is optional, defaulting to ``None``.
    ``package`` may be ``None``.  If ``package`` is ``None``, the
    ``filename`` passed or the value in the ``options`` dictionary
    named ``configure_zcml`` must be a) absolute pathname to a
    :term:`ZCML` file that represents the application's configuration
    *or* b) a :term:`resource specification` to a :term:`ZCML` file in
    the form ``dotted.package.name:relative/file/path.zcml``.

    ``filename`` is the filesystem path to a ZCML file (optionally
    relative to the package path) that should be parsed to create the
    application registry.  It defaults to ``configure.zcml``.  It can
    also be a ;term:`resource specification` in the form
    ``dotted_package_name:relative/file/path.zcml``. Note that if any
    value for ``configure_zcml`` is passed within the ``settings``
    dictionary, the value passed as ``filename`` will be ignored,
    replaced with the ``configure_zcml`` value.

    ``settings``, if used, should be a dictionary containing runtime
    settings (e.g. the key/value pairs in an app section of a
    PasteDeploy file), with each key representing the option and the
    key's value representing the specific option value,
    e.g. ``{'reload_templates':True}``.  Note that the keyword
    parameter ``options`` is a backwards compatibility alias for the
    ``settings`` keyword parameter.
    """
    settings = settings or options or {}
    zcml_file = settings.get('configure_zcml', filename)
    config = Configurator(package=package, settings=settings,
                          root_factory=root_factory)
    config.hook_zca()
    config.begin()
    config.load_zcml(zcml_file)
    config.end()
    return config.make_wsgi_app()

class ActionPredicate(object):
    action_name = 'action'
    def __init__(self, action):
        self.action = action
        try:
            self.action_re = re.compile(action + '$')
        except (re.error, TypeError), why:
            raise ConfigurationError(why[0])

    def __call__(self, context, request):
        matchdict = request.matchdict
        if matchdict is None:
            return False
        action = matchdict.get(self.action_name)
        if action is None:
            return False
        return bool(self.action_re.match(action))

    def __hash__(self):
        # allow this predicate's phash to be compared as equal to
        # others that share the same action name
        return hash(self.action)

