import { useState, useRef } from 'react';
import { api } from '../services/api';
import { Button } from './ui/button';

export default function BookUploader({ onUploadStart, onUploadSuccess, onError }) {
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const fileInputRef = useRef(null);

  const handleDrag = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setIsDragging(true);
    } else if (e.type === 'dragleave') {
      setIsDragging(false);
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFile(e.dataTransfer.files[0]);
    }
  };

  const handleFileChange = (e) => {
    e.preventDefault();
    if (e.target.files && e.target.files[0]) {
      handleFile(e.target.files[0]);
    }
  };

  const handleFile = async (file) => {
    setIsUploading(true);
    onUploadStart();
    try {
      const data = await api.uploadBook(file);
      onUploadSuccess(data.job_id);
    } catch (err) {
      onError(err.message);
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="mx-auto w-full max-w-3xl">
      <h2 className="mb-2 text-center text-xl font-semibold text-slate-50">Upload a new book</h2>
      <p className="mb-8 text-center text-sm text-slate-400">
        PDF, TXT, or Markdown supported
      </p>
      
      <div 
        className={`rounded-2xl border-2 border-dashed p-12 text-center transition ${
          isDragging
            ? 'border-blue-400 bg-blue-500/10 shadow-glow'
            : 'border-slate-700 bg-slate-950/40 hover:border-blue-500/60 hover:bg-blue-500/5'
        }`}
        onDragEnter={handleDrag}
        onDragLeave={handleDrag}
        onDragOver={handleDrag}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current.click()}
      >
        <div className="mx-auto mb-4 w-fit text-slate-400">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="17 8 12 3 7 8" />
            <line x1="12" y1="3" x2="12" y2="15" />
          </svg>
        </div>
        <h3 className="text-base font-medium text-slate-200">{isDragging ? 'Drop it here!' : 'Click or drag a file to upload'}</h3>
        <input 
          type="file" 
          ref={fileInputRef} 
          style={{ display: 'none' }} 
          onChange={handleFileChange}
        />
        {isUploading && <p className="mt-4 text-sm text-blue-700 dark:text-blue-300">Uploading to server...</p>}
        <Button
          className="mt-6"
          onClick={(e) => {
            e.stopPropagation();
            fileInputRef.current?.click();
          }}
        >
          Select file
        </Button>
      </div>
    </div>
  );
}
