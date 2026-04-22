// hooks/useAtlasWebSocket.ts

import { useState, useEffect, useCallback, useRef } from 'react';
import { Client } from '@stomp/stompjs';
import SockJS from 'sockjs-client';

export type MessageRole = 'user' | 'ai';

export interface ChatMessage {
  role: MessageRole;
  content: string;
}

export type ConnectionStatus = 'CONNECTED' | 'DISCONNECTED' | 'CONNECTING';

export function useAtlasWebSocket(url: string = 'http://localhost:8080/atlas-ws') {
  const [status, setStatus] = useState<ConnectionStatus>('CONNECTING');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [terminalLogs, setTerminalLogs] = useState<string[]>([]);
  const [isWorking, setIsWorking] = useState<boolean>(false);
  
  const clientRef = useRef<Client | null>(null);

  useEffect(() => {
    const client = new Client({
      webSocketFactory: () => new SockJS(url),
      reconnectDelay: 5000, 
      onConnect: () => {
        setStatus('CONNECTED');

        client.subscribe('/topic/responses', (message) => {
          const chunk = message.body;
          if (chunk === '[DONE]') {
             setIsWorking(false);
             return;
          }
          setMessages((prev) => {
            if (prev.length === 0) return [{ role: 'ai', content: chunk }];
            
            const lastMsg = prev[prev.length - 1];
            if (lastMsg.role === 'ai') {
              return [
                ...prev.slice(0, -1),
                { ...lastMsg, content: lastMsg.content + chunk },
              ];
            } else {
              return [...prev, { role: 'ai', content: chunk }];
            }
          });
        });

        client.subscribe('/topic/terminal', (message) => {
          setTerminalLogs((prev) => [...prev, message.body]);
        });
      },
      onDisconnect: () => {
        setStatus('DISCONNECTED');
      },
      onWebSocketError: (error) => {
        console.error('WebSocket Error:', error);
        setStatus('DISCONNECTED');
      },
    });

    client.activate();
    clientRef.current = client;

    return () => {
      client.deactivate();
      setStatus('DISCONNECTED');
      clientRef.current = null;
    };
  }, [url]);

  const sendMessage = useCallback((text: string) => {
    if (!text.trim()) return;

    setMessages((prev) => [...prev, { role: 'user', content: text }]);
    setIsWorking(true);

    if (clientRef.current && clientRef.current.connected) {
      clientRef.current.publish({
        destination: '/app/execute',
        body: JSON.stringify({ message: text }),
      });
    } else {
      console.warn('Cannot send message: STOMP client is not connected.');
    }
  }, []);

  // --- THE FIX: Forcefully abort the connection to stop generation ---
  const stopGeneration = useCallback(() => {
    setIsWorking(false);
    if (clientRef.current) {
      clientRef.current.deactivate();
      // Reboot the connection after a tiny delay so it's ready for the next prompt
      setTimeout(() => {
        clientRef.current?.activate();
      }, 500);
    }
  }, []);

  const addTerminalLog = useCallback((log: string) => {
    setTerminalLogs((prev) => [...prev, log]);
  }, []);

  return {
    status,
    messages,
    terminalLogs,
    isWorking,
    sendMessage,
    stopGeneration,
    addTerminalLog,
  };
}