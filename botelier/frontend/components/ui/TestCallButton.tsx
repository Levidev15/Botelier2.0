/**
 * TestCallButton - Browser-based assistant testing
 * 
 * Provides instant voice testing without requiring phone numbers.
 * Opens modal with WebSocket audio streaming to test assistant configuration.
 */

"use client";

import { useState } from 'react';
import { Phone, PhoneOff, AlertCircle } from 'lucide-react';
import { useTestCall } from '@/lib/hooks/useTestCall';

interface TestCallButtonProps {
  assistantId: string;
  assistantName: string;
}

export default function TestCallButton({ assistantId, assistantName }: TestCallButtonProps) {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const { status, error, startCall, endCall } = useTestCall(assistantId);

  const handleStartTest = async () => {
    setIsModalOpen(true);
    await startCall();
  };

  const handleEndTest = () => {
    endCall();
    setIsModalOpen(false);
  };

  const statusConfig = {
    idle: { color: 'bg-gray-500', text: 'Ready' },
    connecting: { color: 'bg-yellow-500', text: 'Connecting...' },
    connected: { color: 'bg-green-500', text: 'Connected' },
    disconnected: { color: 'bg-gray-500', text: 'Disconnected' },
    error: { color: 'bg-red-500', text: 'Error' },
  };

  const currentStatus = statusConfig[status];

  return (
    <>
      <button
        onClick={handleStartTest}
        className="inline-flex items-center px-4 py-2 border border-gray-700 rounded-lg text-sm font-medium text-gray-200 bg-gray-800 hover:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-gray-900 focus:ring-indigo-500 transition-colors"
      >
        <Phone className="h-4 w-4 mr-2" />
        Test Call
      </button>

      {isModalOpen && (
        <div className="fixed inset-0 bg-black bg-opacity-75 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-800 rounded-lg shadow-xl max-w-md w-full p-6 border border-gray-700">
            <div className="flex items-start justify-between mb-4">
              <div>
                <h3 className="text-lg font-semibold text-white">Test Call</h3>
                <p className="text-sm text-gray-400 mt-1">{assistantName}</p>
              </div>
              <button
                onClick={handleEndTest}
                className="text-gray-400 hover:text-white transition-colors"
              >
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <div className="space-y-4">
              <div className="flex items-center justify-between p-4 bg-gray-900 rounded-lg">
                <div className="flex items-center space-x-3">
                  <div className={`w-3 h-3 rounded-full ${currentStatus.color} ${status === 'connecting' ? 'animate-pulse' : ''}`} />
                  <span className="text-sm text-gray-300">{currentStatus.text}</span>
                </div>
                {status === 'connected' && (
                  <div className="flex items-center space-x-2">
                    <div className="flex space-x-1">
                      <div className="w-1 h-4 bg-green-500 animate-pulse" style={{ animationDelay: '0ms' }} />
                      <div className="w-1 h-6 bg-green-500 animate-pulse" style={{ animationDelay: '100ms' }} />
                      <div className="w-1 h-5 bg-green-500 animate-pulse" style={{ animationDelay: '200ms' }} />
                    </div>
                  </div>
                )}
              </div>

              {error && (
                <div className="flex items-start space-x-2 p-3 bg-red-900/20 border border-red-800 rounded-lg">
                  <AlertCircle className="h-5 w-5 text-red-400 flex-shrink-0 mt-0.5" />
                  <div>
                    <p className="text-sm text-red-300 font-medium">Error</p>
                    <p className="text-xs text-red-400 mt-1">{error}</p>
                  </div>
                </div>
              )}

              {status === 'connected' && (
                <div className="p-4 bg-gray-900 rounded-lg border border-gray-700">
                  <p className="text-sm text-gray-300 text-center">
                    🎤 Speak to test your assistant
                  </p>
                  <p className="text-xs text-gray-500 text-center mt-2">
                    Your microphone is active
                  </p>
                </div>
              )}

              {status === 'connecting' && (
                <div className="p-4 bg-gray-900 rounded-lg">
                  <p className="text-sm text-gray-400 text-center">
                    Establishing connection and accessing microphone...
                  </p>
                </div>
              )}

              <div className="flex justify-end space-x-3 pt-2">
                {(status === 'connected' || status === 'connecting') ? (
                  <button
                    onClick={handleEndTest}
                    className="inline-flex items-center px-4 py-2 border border-red-600 rounded-lg text-sm font-medium text-red-400 bg-red-900/20 hover:bg-red-900/40 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-gray-800 focus:ring-red-500 transition-colors"
                  >
                    <PhoneOff className="h-4 w-4 mr-2" />
                    End Call
                  </button>
                ) : (
                  <button
                    onClick={handleEndTest}
                    className="inline-flex items-center px-4 py-2 border border-gray-600 rounded-lg text-sm font-medium text-gray-300 bg-gray-700 hover:bg-gray-600 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-gray-800 focus:ring-gray-500 transition-colors"
                  >
                    Close
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
