import type { CSSProperties } from "react"
import * as React from "react"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  SidebarMenuSubItem,
} from "@/components/ui/sidebar"
import { useSidebar } from "@/components/ui/sidebar/context"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Button } from "@/components/ui/button"
import {
  BarChart3,
  ChevronDown,
  ChevronRight,
  ChevronsUpDown,
  Cloud,
  Folder,
  LogOut,
  PanelLeftIcon,
  Plus,
  Radar,
  Send,
  Settings,
  Shield,
  UserPlus,
  Users,
} from "lucide-react"
import { NavLink, useLocation } from "react-router-dom"

type DashboardSidebarProps = React.ComponentProps<typeof Sidebar>

const navItems = [
  { title: "任务发布", icon: Send, href: "/task-publish" },
  { title: "素材管理", icon: Folder, href: "/materials" },
  { title: "账号管理", icon: Users, href: "/accounts" },
  { title: "数据监控", icon: BarChart3 },
]

const sourceGroups = [
  {
    id: "proxy-pools",
    name: "代理池",
    icon: Shield,
    children: [
      {
        id: "publish-proxy",
        name: "发布代理池",
        icon: Cloud,
        href: "/proxy-pools/publish",
      },
      {
        id: "monitor-proxy",
        name: "监控代理池",
        icon: Radar,
        href: "/proxy-pools/monitor",
      },
    ],
  },
]

export function DashboardSidebar({ ...props }: DashboardSidebarProps) {
  const { toggleSidebar } = useSidebar()
  const location = useLocation()
  const [expandedItems, setExpandedItems] = React.useState<string[]>([
    "proxy-pools",
  ])

  const squareTheme = {
    "--background": "oklch(0.145 0 0)",
    "--foreground": "oklch(0.985 0 0)",
    "--card": "oklch(0.205 0 0)",
    "--card-foreground": "oklch(0.985 0 0)",
    "--popover": "oklch(0.205 0 0)",
    "--popover-foreground": "oklch(0.985 0 0)",
    "--primary": "oklch(0.922 0 0)",
    "--primary-foreground": "oklch(0.205 0 0)",
    "--secondary": "oklch(0.269 0 0)",
    "--secondary-foreground": "oklch(0.985 0 0)",
    "--muted": "oklch(0.269 0 0)",
    "--muted-foreground": "oklch(0.708 0 0)",
    "--accent": "oklch(0.269 0 0)",
    "--accent-foreground": "oklch(0.985 0 0)",
    "--border": "oklch(1 0 0 / 10%)",
    "--input": "oklch(1 0 0 / 15%)",
    "--ring": "oklch(0.556 0 0)",
    "--sidebar": "oklch(0 0 0)",
    "--sidebar-foreground": "oklch(0.985 0 0)",
    "--sidebar-primary": "oklch(0.488 0.243 264.376)",
    "--sidebar-primary-foreground": "oklch(0.985 0 0)",
    "--sidebar-accent": "oklch(0.269 0 0)",
    "--sidebar-accent-foreground": "oklch(0.985 0 0)",
    "--sidebar-border": "oklch(1 0 0 / 10%)",
    "--sidebar-ring": "oklch(0.556 0 0)",
  } as CSSProperties

  const toggleItem = (id: string) => {
    setExpandedItems((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]
    )
  }

  return (
    <Sidebar
      className="lg:border-r-0! dark"
      style={squareTheme}
      collapsible="icon"
      {...props}
    >
      <SidebarHeader className="px-2.5 py-3">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button className="flex w-full items-center gap-2.5 rounded-md p-1 -m-1 transition-colors hover:bg-sidebar-accent shrink-0">
              <div className="flex size-7 items-center justify-center rounded-lg bg-foreground text-background shrink-0">
                <span className="text-sm font-bold">M</span>
              </div>
              <div className="flex items-center gap-1 group-data-[collapsible=icon]:hidden">
                <span className="text-sm font-medium">MCN Console</span>
                <ChevronsUpDown className="size-3 text-muted-foreground ml-auto" />
              </div>
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-56">
            <DropdownMenuItem>
              <Settings className="size-4" />
              <span>工作区设置</span>
            </DropdownMenuItem>
            <DropdownMenuItem>
              <UserPlus className="size-4" />
              <span>邀请协作者</span>
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem className="text-destructive focus:text-destructive">
              <LogOut className="size-4" />
              <span>退出登录</span>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarHeader>

      <SidebarContent className="px-2.5">
        <SidebarGroup className="p-0">
          <SidebarGroupLabel className="px-0 text-[10px] tracking-wider uppercase text-muted-foreground">
            Workspace
          </SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {navItems.map((item) => (
                <SidebarMenuItem key={item.title}>
                  {item.href ? (
                    <SidebarMenuButton
                      asChild
                      isActive={location.pathname === item.href}
                      className="h-8"
                    >
                      <NavLink to={item.href}>
                        <item.icon className="size-4" />
                        <span className="text-sm">{item.title}</span>
                      </NavLink>
                    </SidebarMenuButton>
                  ) : (
                    <SidebarMenuButton className="h-8">
                      <item.icon className="size-4" />
                      <span className="text-sm">{item.title}</span>
                    </SidebarMenuButton>
                  )}
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup className="p-0 mt-4">
          <SidebarGroupLabel className="flex h-6 items-center justify-between px-0">
            <span className="text-[10px] font-medium tracking-wider text-muted-foreground uppercase">
              数据源
            </span>
            <Button variant="ghost" size="icon" className="size-5">
              <Plus className="size-3" />
            </Button>
          </SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {sourceGroups.map((item) => {
                const isExpanded = expandedItems.includes(item.id)
                return (
                  <SidebarMenuItem key={item.id}>
                    <Collapsible
                      open={isExpanded}
                      onOpenChange={() => toggleItem(item.id)}
                    >
                      <CollapsibleTrigger asChild>
                        <SidebarMenuButton className="h-7 text-sm">
                          <item.icon className="size-3.5" />
                          <span className="flex-1">{item.name}</span>
                          {isExpanded ? (
                            <ChevronDown className="size-3" />
                          ) : (
                            <ChevronRight className="size-3" />
                          )}
                        </SidebarMenuButton>
                      </CollapsibleTrigger>
                      <CollapsibleContent>
                        <SidebarMenuSub className="mr-0 pr-0">
                          {item.children.map((child) => (
                            <SidebarMenuSubItem key={child.id}>
                              {"href" in child && child.href ? (
                                <SidebarMenuButton
                                  asChild
                                  isActive={location.pathname === child.href}
                                  className="h-7 text-sm pl-6"
                                >
                                  <NavLink to={child.href}>
                                    <child.icon className="size-3.5" />
                                    <span>{child.name}</span>
                                  </NavLink>
                                </SidebarMenuButton>
                              ) : (
                                <SidebarMenuButton className="h-7 text-sm pl-6">
                                  <child.icon className="size-3.5" />
                                  <span>{child.name}</span>
                                </SidebarMenuButton>
                              )}
                            </SidebarMenuSubItem>
                          ))}
                        </SidebarMenuSub>
                      </CollapsibleContent>
                    </Collapsible>
                  </SidebarMenuItem>
                )
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter className="px-2.5 pb-3">
        <div className="group-data-[collapsible=icon]:hidden">
          <div className="group/sidebar relative flex flex-col gap-2 rounded-lg border p-4 text-sm w-full bg-background">
            <div className="text-balance text-lg font-semibold leading-tight group-hover/sidebar:underline">
              Global content workflow, built for scale.
            </div>
            <div className="text-muted-foreground">
              聚合采集、素材编排、定时发布与数据监控的统一操作台。
            </div>
            <Button size="sm" className="w-full">
              创建发布任务
            </Button>
          </div>
        </div>

        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton className="h-7 text-sm" onClick={toggleSidebar}>
              <PanelLeftIcon className="size-3.5" />
              <span>收起侧栏</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  )
}
