import unittest

class TestDottedNameResolver(unittest.TestCase):
    def _makeOne(self, package=None):
        from pyramid.util import DottedNameResolver
        return DottedNameResolver(package)

    def config_exc(self, func, *arg, **kw):
        from pyramid.exceptions import ConfigurationError
        try:
            func(*arg, **kw)
        except ConfigurationError, e:
            return e
        else:
            raise AssertionError('Invalid not raised') # pragma: no cover

    def test_zope_dottedname_style_resolve_absolute(self):
        typ = self._makeOne()
        result = typ._zope_dottedname_style(
            'pyramid.tests.test_util.TestDottedNameResolver')
        self.assertEqual(result, self.__class__)

    def test_zope_dottedname_style_irrresolveable_absolute(self):
        typ = self._makeOne()
        self.assertRaises(ImportError, typ._zope_dottedname_style,
            'pyramid.test_util.nonexisting_name')

    def test__zope_dottedname_style_resolve_relative(self):
        import pyramid.tests
        typ = self._makeOne(package=pyramid.tests)
        result = typ._zope_dottedname_style(
            '.test_util.TestDottedNameResolver')
        self.assertEqual(result, self.__class__)

    def test__zope_dottedname_style_resolve_relative_leading_dots(self):
        import pyramid.tests.test_configuration
        typ = self._makeOne(package=pyramid.tests)
        result = typ._zope_dottedname_style(
            '..tests.test_util.TestDottedNameResolver')
        self.assertEqual(result, self.__class__)

    def test__zope_dottedname_style_resolve_relative_is_dot(self):
        import pyramid.tests
        typ = self._makeOne(package=pyramid.tests)
        result = typ._zope_dottedname_style('.')
        self.assertEqual(result, pyramid.tests)

    def test__zope_dottedname_style_irresolveable_relative_is_dot(self):
        typ = self._makeOne()
        e = self.config_exc(typ._zope_dottedname_style, '.')
        self.assertEqual(
            e.args[0],
            "relative name '.' irresolveable without package")

    def test_zope_dottedname_style_resolve_relative_nocurrentpackage(self):
        typ = self._makeOne()
        e = self.config_exc(typ._zope_dottedname_style, '.whatever')
        self.assertEqual(
            e.args[0],
            "relative name '.whatever' irresolveable without package")

    def test_zope_dottedname_style_irrresolveable_relative(self):
        import pyramid.tests
        typ = self._makeOne(package=pyramid.tests)
        self.assertRaises(ImportError, typ._zope_dottedname_style,
                          '.notexisting')

    def test__zope_dottedname_style_resolveable_relative(self):
        import pyramid
        typ = self._makeOne(package=pyramid)
        result = typ._zope_dottedname_style('.tests')
        from pyramid import tests
        self.assertEqual(result, tests)

    def test__zope_dottedname_style_irresolveable_absolute(self):
        typ = self._makeOne()
        self.assertRaises(
            ImportError,
            typ._zope_dottedname_style, 'pyramid.fudge.bar')

    def test__zope_dottedname_style_resolveable_absolute(self):
        typ = self._makeOne()
        result = typ._zope_dottedname_style(
            'pyramid.tests.test_util.TestDottedNameResolver')
        self.assertEqual(result, self.__class__)

    def test__pkg_resources_style_resolve_absolute(self):
        typ = self._makeOne()
        result = typ._pkg_resources_style(
            'pyramid.tests.test_util:TestDottedNameResolver')
        self.assertEqual(result, self.__class__)

    def test__pkg_resources_style_irrresolveable_absolute(self):
        typ = self._makeOne()
        self.assertRaises(ImportError, typ._pkg_resources_style,
            'pyramid.tests:nonexisting')

    def test__pkg_resources_style_resolve_relative(self):
        import pyramid.tests
        typ = self._makeOne(package=pyramid.tests)
        result = typ._pkg_resources_style(
            '.test_util:TestDottedNameResolver')
        self.assertEqual(result, self.__class__)

    def test__pkg_resources_style_resolve_relative_is_dot(self):
        import pyramid.tests
        typ = self._makeOne(package=pyramid.tests)
        result = typ._pkg_resources_style('.')
        self.assertEqual(result, pyramid.tests)

    def test__pkg_resources_style_resolve_relative_nocurrentpackage(self):
        typ = self._makeOne()
        from pyramid.exceptions import ConfigurationError
        self.assertRaises(ConfigurationError, typ._pkg_resources_style,
                          '.whatever')

    def test__pkg_resources_style_irrresolveable_relative(self):
        import pyramid
        typ = self._makeOne(package=pyramid)
        self.assertRaises(ImportError, typ._pkg_resources_style,
                          ':notexisting')

    def test_resolve_not_a_string(self):
        typ = self._makeOne()
        e = self.config_exc(typ.resolve, None)
        self.assertEqual(e.args[0], 'None is not a string')

    def test_resolve_using_pkgresources_style(self):
        typ = self._makeOne()
        result = typ.resolve(
            'pyramid.tests.test_util:TestDottedNameResolver')
        self.assertEqual(result, self.__class__)

    def test_resolve_using_zope_dottedname_style(self):
        typ = self._makeOne()
        result = typ.resolve(
            'pyramid.tests.test_util:TestDottedNameResolver')
        self.assertEqual(result, self.__class__)

    def test_resolve_missing_raises(self):
        typ = self._makeOne()
        self.assertRaises(ImportError, typ.resolve, 'cant.be.found')

    def test_ctor_string_module_resolveable(self):
        import pyramid.tests
        typ = self._makeOne('pyramid.tests.test_util')
        self.assertEqual(typ.package, pyramid.tests)
        self.assertEqual(typ.package_name, 'pyramid.tests')

    def test_ctor_string_package_resolveable(self):
        import pyramid.tests
        typ = self._makeOne('pyramid.tests')
        self.assertEqual(typ.package, pyramid.tests)
        self.assertEqual(typ.package_name, 'pyramid.tests')

    def test_ctor_string_irresolveable(self):
        from pyramid.configuration import ConfigurationError
        self.assertRaises(ConfigurationError, self._makeOne, 'cant.be.found')

    def test_ctor_module(self):
        import pyramid.tests
        import pyramid.tests.test_util
        typ = self._makeOne(pyramid.tests.test_util)
        self.assertEqual(typ.package, pyramid.tests)
        self.assertEqual(typ.package_name, 'pyramid.tests')

    def test_ctor_package(self):
        import pyramid.tests
        typ = self._makeOne(pyramid.tests)
        self.assertEqual(typ.package, pyramid.tests)
        self.assertEqual(typ.package_name, 'pyramid.tests')

    def test_ctor_None(self):
        typ = self._makeOne(None)
        self.assertEqual(typ.package, None)
        self.assertEqual(typ.package_name, None)

