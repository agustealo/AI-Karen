import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { validateRawManifest, type RawManifestValidationResult } from '../../src/plugin_host/manifest-validator';
import type { UIManifest } from '../../src/plugin_host/manifest-validator';

// Mock console to avoid noise during tests
const originalConsoleError = console.error;
beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
});
afterEach(() => {
  vi.restoreAllMocks();
  console.error = originalConsoleError;
});

describe('Manifest Validator', () => {
  describe('Valid Manifests', () => {
    it('should accept a complete valid manifest', () => {
      const validManifest: UIManifest = {
        plugin_id: 'weather-query',
        component: 'WeatherPluginPage',
        slots: ['sidebar.plugins'],
        permissions: ['user', 'admin'],
        display_name: 'Weather Services',
        icon: 'weather-query---sidebar_00.svg',
        order: 0,
        label: 'Weather'
      };

      const result = validateRawManifest(validManifest, 'weather-query');
      
      expect(result).toEqual({
        valid: true,
        manifest: validManifest
      });
    });

    it('should accept manifest with only required fields', () => {
      const minimalManifest: UIManifest = {
        plugin_id: 'test-plugin',
        component: 'TestPluginPage',
        slots: ['sidebar.plugins'],
        permissions: ['user']
      };

      const result = validateRawManifest(minimalManifest, 'test-plugin');
      
      expect(result).toEqual({
        valid: true,
        manifest: minimalManifest
      });
    });

    it('should accept manifest with empty optional fields', () => {
      const manifestWithEmptyOptionals: UIManifest = {
        plugin_id: 'test-plugin',
        component: 'TestPluginPage',
        slots: ['sidebar.plugins'],
        permissions: ['user'],
        display_name: '',
        icon: '',
        order: 0,
        label: ''
      };

      const result = validateRawManifest(manifestWithEmptyOptionals, 'test-plugin');
      
      expect(result).toEqual({
        valid: true,
        manifest: manifestWithEmptyOptionals
      });
    });

    it('should accept manifest with numeric order field', () => {
      const manifestWithOrder: UIManifest = {
        plugin_id: 'test-plugin',
        component: 'TestPluginPage',
        slots: ['sidebar.plugins'],
        permissions: ['user'],
        order: 5
      };

      const result = validateRawManifest(manifestWithOrder, 'test-plugin');
      
      expect(result).toEqual({
        valid: true,
        manifest: manifestWithOrder
      });
    });

    it('should accept manifest with multiple slots', () => {
      const manifestWithMultipleSlots: UIManifest = {
        plugin_id: 'analytics-plugin',
        component: 'AnalyticsPluginPage',
        slots: ['sidebar.plugins', 'page.plugins.overview'],
        permissions: ['admin']
      };

      const result = validateRawManifest(manifestWithMultipleSlots, 'analytics-plugin');
      
      expect(result).toEqual({
        valid: true,
        manifest: manifestWithMultipleSlots
      });
    });
  });

  describe('Invalid Manifests', () => {
    it('should reject manifest with missing plugin_id', () => {
      const invalidManifest = {
        component: 'WeatherPluginPage',
        slots: ['sidebar.plugins'],
        permissions: ['user', 'admin']
      };

      const result = validateRawManifest(invalidManifest as unknown as UIManifest, 'weather-query');
      
      expect(result).toEqual({
        valid: false,
        pluginId: 'weather-query',
        error: 'Missing or invalid required field: plugin_id (must be a non-empty string)'
      });
    });

    it('should reject manifest with missing component', () => {
      const invalidManifest = {
        plugin_id: 'weather-query',
        slots: ['sidebar.plugins'],
        permissions: ['user', 'admin']
      };

      const result = validateRawManifest(invalidManifest as unknown as UIManifest, 'weather-query');
      
      expect(result).toEqual({
        valid: false,
        pluginId: 'weather-query',
        error: 'Missing or invalid required field: component (must be a non-empty string)'
      });
    });

    it('should reject manifest with missing slots', () => {
      const invalidManifest = {
        plugin_id: 'weather-query',
        component: 'WeatherPluginPage',
        permissions: ['user', 'admin']
      };

      const result = validateRawManifest(invalidManifest as unknown as UIManifest, 'weather-query');
      
      expect(result).toEqual({
        valid: false,
        pluginId: 'weather-query',
        error: 'Missing or invalid required field: slots (must be an array of strings)'
      });
    });

    it('should reject manifest with missing permissions', () => {
      const invalidManifest = {
        plugin_id: 'weather-query',
        component: 'WeatherPluginPage',
        slots: ['sidebar.plugins']
      };

      const result = validateRawManifest(invalidManifest as unknown as UIManifest, 'weather-query');
      
      expect(result).toEqual({
        valid: false,
        pluginId: 'weather-query',
        error: 'Missing or invalid required field: permissions (must be an array of strings)'
      });
    });

    it('should reject manifest with invalid plugin_id type', () => {
      const invalidManifest = {
        plugin_id: 123,
        component: 'WeatherPluginPage',
        slots: ['sidebar.plugins'],
        permissions: ['user', 'admin']
      };

      const result = validateRawManifest(invalidManifest as unknown as UIManifest, 'weather-query');
      
      expect(result).toEqual({
        valid: false,
        pluginId: 'weather-query',
        error: 'Missing or invalid required field: plugin_id (must be a non-empty string)'
      });
    });

    it('should reject manifest with invalid component type', () => {
      const invalidManifest = {
        plugin_id: 'weather-query',
        component: 123,
        slots: ['sidebar.plugins'],
        permissions: ['user', 'admin']
      };

      const result = validateRawManifest(invalidManifest as unknown as UIManifest, 'weather-query');
      
      expect(result).toEqual({
        valid: false,
        pluginId: 'weather-query',
        error: 'Missing or invalid required field: component (must be a non-empty string)'
      });
    });

    it('should reject manifest with invalid slots type', () => {
      const invalidManifest = {
        plugin_id: 'weather-query',
        component: 'WeatherPluginPage',
        slots: 'sidebar.plugins',
        permissions: ['user', 'admin']
      };

      const result = validateRawManifest(invalidManifest as unknown as UIManifest, 'weather-query');
      
      expect(result).toEqual({
        valid: false,
        pluginId: 'weather-query',
        error: 'Missing or invalid required field: slots (must be an array of strings)'
      });
    });

    it('should reject manifest with invalid permissions type', () => {
      const invalidManifest = {
        plugin_id: 'weather-query',
        component: 'WeatherPluginPage',
        slots: ['sidebar.plugins'],
        permissions: 'user'
      };

      const result = validateRawManifest(invalidManifest as unknown as UIManifest, 'weather-query');
      
      expect(result).toEqual({
        valid: false,
        pluginId: 'weather-query',
        error: 'Missing or invalid required field: permissions (must be an array of strings)'
      });
    });

    it('should reject manifest with invalid order type', () => {
      const invalidManifest = {
        plugin_id: 'weather-query',
        component: 'WeatherPluginPage',
        slots: ['sidebar.plugins'],
        permissions: ['user', 'admin'],
        order: 'not-a-number'
      };

      const result = validateRawManifest(invalidManifest as unknown as UIManifest, 'weather-query');
      
      expect(result).toEqual({
        valid: false,
        pluginId: 'weather-query',
        error: 'Invalid optional field: order must be an integer'
      });
    });

    it('should reject manifest with invalid slot entries', () => {
      const invalidManifest = {
        plugin_id: 'weather-query',
        component: 'WeatherPluginPage',
        slots: ['sidebar.plugins', 123],
        permissions: ['user', 'admin']
      };

      const result = validateRawManifest(invalidManifest as unknown as UIManifest, 'weather-query');
      
      expect(result).toEqual({
        valid: false,
        pluginId: 'weather-query',
        error: 'Invalid required field: slots must be an array of strings'
      });
    });

    it('should reject manifest with invalid permission entries', () => {
      const invalidManifest = {
        plugin_id: 'weather-query',
        component: 'WeatherPluginPage',
        slots: ['sidebar.plugins'],
        permissions: ['user', 123]
      };

      const result = validateRawManifest(invalidManifest as unknown as UIManifest, 'weather-query');
      
      expect(result).toEqual({
        valid: false,
        pluginId: 'weather-query',
        error: 'Invalid required field: permissions must be an array of strings'
      });
    });

    it('should reject manifest with null values', () => {
      const invalidManifest = {
        plugin_id: null,
        component: 'WeatherPluginPage',
        slots: ['sidebar.plugins'],
        permissions: ['user', 'admin']
      };

      const result = validateRawManifest(invalidManifest as unknown as UIManifest, 'weather-query');
      
      expect(result).toEqual({
        valid: false,
        pluginId: 'weather-query',
        error: 'Missing or invalid required field: plugin_id (must be a non-empty string)'
      });
    });
  });

  describe('Legacy Compatibility', () => {
    it('should accept legacy ui section from plugin_manifest', () => {
      const legacyManifest = {
        has_component: true,
        component_id: 'weather-query',
        menu: [
          {
            placement: 'sidebar',
            label: 'Weather',
            order: 0,
            icon: 'weather-query---sidebar_00.svg'
          }
        ],
        rbac: {
          allowed_roles: ['user', 'admin', 'developer']
        }
      };

      const result = validateRawManifest(legacyManifest, 'weather-query');
      
      expect(result.valid).toBe(true);
      if (result.valid) {
        expect(result.manifest.plugin_id).toBe('weather-query');
        expect(result.manifest.component).toBe('weather-query');
        expect(result.manifest.slots).toEqual(['sidebar.plugins']);
        expect(result.manifest.icon).toBe('weather-query---sidebar_00.svg');
        expect(result.manifest.order).toBe(0);
        expect(result.manifest.label).toBe('Weather');
        expect(result.manifest.permissions).toEqual([]);
      }
    });

    it('should reject legacy manifest with missing required fields', () => {
      const incompleteLegacyManifest = {
        has_component: true
        // Missing component_id, menu
      };

      const result = validateRawManifest(incompleteLegacyManifest, 'weather-query');
      
      expect(result.valid).toBe(false);
      if (!result.valid) {
        expect(result.pluginId).toBe('weather-query');
        expect(result.error).toBeTruthy();
      }
    });
  });

  describe('Error Messages', () => {
    it('should provide detailed error messages for multiple issues', () => {
      const invalidManifest = {
        plugin_id: 123,
        component: 456,
        slots: 'not-an-array',
        permissions: 'not-an-array'
      };

      const result = validateRawManifest(invalidManifest as unknown as UIManifest, 'weather-query');
      
      expect(result.valid).toBe(false);
      if (!result.valid) {
        expect(result.error).toContain('Missing or invalid required field: plugin_id');
      }
    });

    it('should include plugin ID in failure result', () => {
      const invalidManifest = {
        plugin_id: 123,
        component: 'WeatherPluginPage',
        slots: ['sidebar.plugins'],
        permissions: ['user', 'admin']
      };

      const result = validateRawManifest(invalidManifest as unknown as UIManifest, 'test-plugin');
      
      expect(result.valid).toBe(false);
      if (!result.valid) {
        expect(result.pluginId).toBe('test-plugin');
      }
    });
  });
});