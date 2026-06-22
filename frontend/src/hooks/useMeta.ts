import { useQuery } from '@tanstack/react-query';
import { getMeta, getStrategies, getHealth } from '../lib/api';

export function useMeta() {
  const presetsQuery = useQuery({
    queryKey: ['presets'],
    queryFn: getMeta,
    retry: 1,
  });

  const strategiesQuery = useQuery({
    queryKey: ['strategies'],
    queryFn: getStrategies,
    retry: 1,
  });

  const healthQuery = useQuery({
    queryKey: ['health'],
    queryFn: getHealth,
    retry: false,
    refetchInterval: 30000, // 每 30 秒检查一次
  });

  return {
    presets: presetsQuery.data?.presets || [],
    strategies: strategiesQuery.data || [],
    isHealthy: healthQuery.data?.status === 'ok',
    isLoading: presetsQuery.isLoading || strategiesQuery.isLoading,
    error: presetsQuery.error || strategiesQuery.error,
  };
}
