"use client";

import { useState, useEffect, useMemo } from 'react';
import { useAuth } from '@/lib/useAuth';
import { ApiError, apiClient } from '@/lib/api';
 
export class PluginExtensionError extends Error {
  status: number;
  details: string;
 
  constructor(status: number, statusText: string, details: string) {
    super(`Extension execution failed: ${statusText}${details ? ` - ${details}` : ''}`);
    this.name = 'PluginExtensionError';
    this.status = status;
    this.details = details;
  }
}
 
export interface ExtensionAPI {
  execute: (command: unknown) => Promise<unknown>;
  getStatus: () => Promise<{ isReady: boolean; error?: string | null }>;
}
 
export interface UsePluginExtensionReturn {
  api: ExtensionAPI;
  isReady: boolean;
  error: string | null;
  loading: boolean;
}
 
/**
 * Hook for accessing plugin extension APIs from the Karen AI platform.
 * Provides a unified interface for executing plugin commands and managing plugin state.
 */
export function usePluginExtension(pluginId: string): UsePluginExtensionReturn {
  useAuth();
  const [isReady, setIsReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
 
  // Create the API object with execute method - memoized to prevent loops
  const api: ExtensionAPI = useMemo(() => ({
    execute: async (command: unknown) => {
      try {
        const data = await apiClient.post(`/api/plugins/${pluginId}/execute`, {
          plugin_name: pluginId,
          parameters: command
        }) as { success?: boolean; error?: string; result?: unknown };
        
        // Handle the standard PluginExecutionResponse wrapper
        if (data && typeof data === 'object') {
          if (data.success === false) {
            const errorMsg = data.error || 'Plugin execution failed';
            setError(errorMsg);
            throw new Error(errorMsg);
          }
          
          // Return the actual result payload from the plugin
          if ('result' in data) {
            return data.result;
          }
        }
        
        return data;
      } catch (err: unknown) {
        const errorMessage = err instanceof Error ? err.message : 'Unknown error';
        // A throttled command is recoverable; it must not mark the entire
        // extension host unhealthy and replace otherwise usable plugin UI.
        if (!(err instanceof ApiError && err.status === 429)) {
          setError(errorMessage);
        }
        throw err;
      }
    },
 
    getStatus: async () => {
      try {
        const data: unknown = await apiClient.get('/api/plugins/health');
        const statusData = data as { status?: string; error?: string };
        return {
          isReady: statusData.status === 'healthy' || statusData.status === 'ok',
          error: statusData.error || null
        };
      } catch (err: unknown) {
        const errorMessage = err instanceof Error ? err.message : 'Unknown error';
        setError(errorMessage);
        return {
          isReady: false,
          error: errorMessage
        };
      }
    }
  }), [pluginId]);

  // Initialize and check plugin status
  useEffect(() => {
    const initializePlugin = async () => {
      try {
        setLoading(true);
        setError(null);
        
        const status = await api.getStatus();
        setIsReady(status.isReady);
        
        if (status.error) {
          setError(status.error);
        }
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : 'Failed to initialize plugin';
        setError(errorMessage);
        setIsReady(false);
      } finally {
        setLoading(false);
      }
    };

    initializePlugin();
  }, [pluginId, api]);

  return {
    api,
    isReady,
    error,
    loading
  };
}
