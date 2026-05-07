import { useState, useEffect, useRef } from 'react';
import { api } from '../services/api';

export default function ProcessingIndicator({ jobId, onComplete, onError }) {
  const [status, setStatus] = useState('PENDING');
  const [pollErrors, setPollErrors] = useState(0);
  const onCompleteRef = useRef(onComplete);
  const onErrorRef = useRef(onError);

  useEffect(() => {
    onCompleteRef.current = onComplete;
    onErrorRef.current = onError;
  }, [onComplete, onError]);

  useEffect(() => {
    let timeoutId = null;
    let isActive = true;
    
    const poll = async () => {
      try {
        const job = await api.getJobStatus(jobId);
        if (!isActive) return;
        setPollErrors(0);
        setStatus(job.status.toUpperCase());
        
        if (job.status === 'completed' || job.status === 'COMPLETED') {
          onCompleteRef.current(job);
        } else if (job.status === 'failed' || job.status === 'FAILED') {
          onErrorRef.current(job.error_message || 'Processing failed.');
        } else {
          // Keep polling
          timeoutId = setTimeout(poll, 2500);
        }
      } catch (err) {
        if (!isActive) return;
        setPollErrors((prev) => {
          const next = prev + 1;
          if (next >= 5) {
            onErrorRef.current(err.message || 'Unable to track processing status.');
            return next;
          }
          timeoutId = setTimeout(poll, 2500);
          return next;
        });
      }
    };

    poll();

    return () => {
      isActive = false;
      if (timeoutId) clearTimeout(timeoutId);
    };
  }, [jobId]);

  return (
    <div className="flex min-h-[360px] flex-col items-center justify-center text-center">
      <div className="spinner"></div>
      <h2 className="mb-2 mt-3 text-lg font-semibold text-white">Processing Document</h2>
      <p className="text-sm text-slate-400">
        {status === 'PENDING' && 'Waiting in queue...'}
        {status === 'PROCESSING' && 'Extracting text and generating embeddings...'}
        {pollErrors > 0 && status !== 'FAILED' && (
          <span className="mt-1 block text-amber-300">
            Connection hiccup while polling. Retrying...
          </span>
        )}
      </p>
    </div>
  );
}
