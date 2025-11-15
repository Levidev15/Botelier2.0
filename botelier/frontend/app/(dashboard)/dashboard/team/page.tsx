import { Plus, Users, Mail } from "lucide-react";

export default function TeamPage() {
  return (
    <div className="p-8">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h1 className="text-2xl font-bold">Team</h1>
          <p className="text-sm text-gray-400 mt-1">
            Manage team members and permissions
          </p>
        </div>
        <button className="inline-flex items-center px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition text-sm font-medium">
          <Plus className="h-4 w-4 mr-2" />
          Invite Member
        </button>
      </div>

      <div className="bg-[#141414] border border-gray-800 rounded-lg">
        <div className="p-6 border-b border-gray-800">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-4">
              <div className="w-10 h-10 bg-blue-600 rounded-full flex items-center justify-center text-sm font-semibold">
                H
              </div>
              <div>
                <h3 className="font-semibold">Hotel Demo</h3>
                <p className="text-sm text-gray-400">hotel@example.com</p>
              </div>
            </div>
            <span className="px-3 py-1 bg-blue-600/10 text-blue-400 rounded-full text-xs font-medium">
              Owner
            </span>
          </div>
        </div>

        <div className="p-12 text-center">
          <Users className="h-12 w-12 text-gray-600 mx-auto mb-4" />
          <h3 className="text-lg font-semibold mb-2">Invite your team</h3>
          <p className="text-sm text-gray-400 mb-6">
            Collaborate with your team on voice assistants
          </p>
          <button className="inline-flex items-center px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition text-sm font-medium">
            <Mail className="h-4 w-4 mr-2" />
            Send Invitation
          </button>
        </div>
      </div>
    </div>
  );
}
