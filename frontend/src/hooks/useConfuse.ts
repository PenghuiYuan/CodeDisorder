import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { postConfuse, ConfuseRequest } from '../lib/api';

export function useConfuse() {
  const [isRunning, setIsRunning] = useState(false);

  const mutation = useMutation({
    mutationFn: (request: ConfuseRequest) => postConfuse(request),
    onMutate: () => {
      setIsRunning(true);
    },
    onSettled: () => {
      setIsRunning(false);
    },
  });

  return {
    confuse: mutation.mutate,
    confuseAsync: mutation.mutateAsync,
    isRunning,
    result: mutation.data,
    error: mutation.error,
    reset: () => mutation.reset(),
  };
}
