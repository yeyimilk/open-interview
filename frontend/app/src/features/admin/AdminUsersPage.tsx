import {
  RefreshCw,
  ShieldCheck,
  ShieldOff,
  Users,
} from "lucide-react";
import { useEffect, useMemo, useState, type ElementType } from "react";
import { toast } from "sonner";
import { UserOut, api } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { PageHeader } from "../../components/common/PageHeader";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent } from "../../components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../../components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../../components/ui/table";

const DEFAULT_TIERS = ["free", "pro", "team", "enterprise"];

export function AdminUsersPage() {
  const { user, refresh } = useAuth();
  const [users, setUsers] = useState<UserOut[]>([]);
  const [loading, setLoading] = useState(false);
  const [busyUserId, setBusyUserId] = useState<string | null>(null);

  const adminCount = users.filter((u) => u.is_admin).length;
  const tierOptions = useMemo(
    () =>
      Array.from(
        new Set([...DEFAULT_TIERS, ...users.map((u) => u.tier).filter(Boolean)])
      ),
    [users]
  );

  async function loadUsers() {
    if (!user?.is_admin) return;
    setLoading(true);
    try {
      setUsers(await api.adminListUsers());
    } catch (e) {
      toast.error("Failed to load users", {
        description: (e as Error).message,
      });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadUsers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.is_admin]);

  async function updateUser(
    target: UserOut,
    body: { tier?: string | null; is_admin?: boolean | null }
  ) {
    setBusyUserId(target.id);
    try {
      const updated = await api.adminUpdateUser(target.id, body);
      setUsers((prev) => prev.map((u) => (u.id === updated.id ? updated : u)));
      if (updated.id === user?.id) {
        await refresh();
      }
      toast.success("User updated");
    } catch (e) {
      toast.error("Update failed", { description: (e as Error).message });
    } finally {
      setBusyUserId(null);
    }
  }

  if (!user?.is_admin) {
    return (
      <Card>
        <CardContent className="py-8 text-sm text-muted-foreground">
          Admin access is required.
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="User Admin"
        description="Manage account roles and plan tiers."
        actions={
          <Button variant="outline" onClick={() => void loadUsers()} disabled={loading}>
            <RefreshCw className="h-4 w-4" /> Refresh
          </Button>
        }
      />

      <div className="grid gap-4 sm:grid-cols-3">
        <MetricCard label="Users" value={users.length} icon={Users} />
        <MetricCard label="Admins" value={adminCount} icon={ShieldCheck} />
        <MetricCard
          label="Standard"
          value={Math.max(users.length - adminCount, 0)}
          icon={ShieldOff}
        />
      </div>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>User</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Tier</TableHead>
                <TableHead>Created</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {users.map((u) => {
                const busy = busyUserId === u.id;
                const removingLastAdmin = u.is_admin && adminCount <= 1;
                return (
                  <TableRow key={u.id}>
                    <TableCell>
                      <div className="font-medium">{u.display_name || u.email}</div>
                      <div className="text-xs text-muted-foreground">{u.email}</div>
                    </TableCell>
                    <TableCell>
                      <Badge variant={u.is_admin ? "default" : "muted"}>
                        {u.is_admin ? "Admin" : "User"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Select
                        value={u.tier}
                        disabled={busy}
                        onValueChange={(tier) => void updateUser(u, { tier })}
                      >
                        <SelectTrigger className="h-9 w-[9rem]">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {tierOptions.map((tier) => (
                            <SelectItem key={tier} value={tier}>
                              {tier}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatDate(u.created_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant={u.is_admin ? "outline" : "default"}
                        size="sm"
                        disabled={busy || removingLastAdmin}
                        onClick={() => void updateUser(u, { is_admin: !u.is_admin })}
                      >
                        {u.is_admin ? (
                          <>
                            <ShieldOff className="h-4 w-4" /> Remove admin
                          </>
                        ) : (
                          <>
                            <ShieldCheck className="h-4 w-4" /> Make admin
                          </>
                        )}
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
              {users.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-muted-foreground">
                    No users found.
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

function MetricCard({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: number;
  icon: ElementType;
}) {
  return (
    <Card>
      <CardContent className="flex items-center justify-between p-4">
        <div>
          <div className="text-sm text-muted-foreground">{label}</div>
          <div className="text-2xl font-semibold">{value}</div>
        </div>
        <div className="grid h-10 w-10 place-items-center rounded-lg bg-primary/10 text-primary">
          <Icon className="h-5 w-5" />
        </div>
      </CardContent>
    </Card>
  );
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(value));
}
