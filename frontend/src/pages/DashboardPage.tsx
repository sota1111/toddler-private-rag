import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { getTomorrow, getWeekly, getPending } from '../api';
import type { NurseryInfo } from '../types';

const DashboardSection: React.FC<{
  title: string;
  items: NurseryInfo[];
  isLoading: boolean;
  renderItem: (item: NurseryInfo) => React.ReactNode;
  headerColor: string;
}> = ({ title, items, isLoading, renderItem, headerColor }) => (
  <div className="bg-white rounded-lg shadow-md overflow-hidden mb-6">
    <div className={`${headerColor} px-4 py-2 text-white font-bold`}>
      {title}
    </div>
    <div className="p-4">
      {isLoading ? (
        <p className="text-gray-500">読み込み中...</p>
      ) : items.length === 0 ? (
        <p className="text-gray-400 text-sm">データなし</p>
      ) : (
        <ul className="divide-y divide-gray-100">
          {items.map((item) => (
            <li key={item.id} className="py-2">
              {renderItem(item)}
            </li>
          ))}
        </ul>
      )}
    </div>
  </div>
);

const DashboardPage: React.FC = () => {
  const tomorrowQuery = useQuery({ queryKey: ['tomorrow'], queryFn: getTomorrow });
  const weeklyQuery = useQuery({ queryKey: ['weekly'], queryFn: getWeekly });
  const pendingQuery = useQuery({ queryKey: ['pending'], queryFn: getPending });

  return (
    <div className="w-full lg:max-w-6xl lg:mx-auto">
      <h1 className="text-2xl font-bold mb-6 text-gray-800">ダッシュボード</h1>
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <DashboardSection
          title="明日の持ち物"
          items={tomorrowQuery.data || []}
          isLoading={tomorrowQuery.isLoading}
          headerColor="bg-blue-500"
          renderItem={(item) => (
            <div>
              <p className="font-medium text-gray-800">{item.title}</p>
              {item.items && <p className="text-sm text-gray-600">持物: {item.items}</p>}
            </div>
          )}
        />

        <DashboardSection
          title="今週の行事"
          items={weeklyQuery.data || []}
          isLoading={weeklyQuery.isLoading}
          headerColor="bg-green-500"
          renderItem={(item) => (
            <div className="flex justify-between items-center">
              <span className="font-medium text-gray-800">{item.title}</span>
              <span className="text-xs bg-green-100 text-green-800 px-2 py-1 rounded">
                {item.event_date}
              </span>
            </div>
          )}
        />

        <DashboardSection
          title="未対応の提出物"
          items={pendingQuery.data || []}
          isLoading={pendingQuery.isLoading}
          headerColor="bg-red-500"
          renderItem={(item) => (
            <div className="flex justify-between items-center">
              <div>
                <p className="font-medium text-gray-800">{item.title}</p>
                {item.due_date && <p className="text-xs text-red-600 font-semibold">期限: {item.due_date}</p>}
              </div>
              <span className="text-xs bg-red-100 text-red-800 px-2 py-1 rounded">
                {item.priority}
              </span>
            </div>
          )}
        />
      </div>
    </div>
  );
};

export default DashboardPage;
