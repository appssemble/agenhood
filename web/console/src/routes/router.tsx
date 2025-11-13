import { createBrowserRouter, type RouteObject, Navigate } from "react-router-dom";
import { AuthProvider } from "../auth/AuthProvider";
import { AppShell } from "../components/AppShell";
import { RequireRole } from "../components/RequireRole";
import Login from "../pages/Login";
import ChangePassword from "../pages/ChangePassword";
import Dashboard from "../pages/Dashboard";
import Containers from "../pages/Containers";
import ContainerLayout from "../pages/ContainerLayout";
import ContainerOverview from "../pages/ContainerOverview";
import Configuration from "../pages/Configuration";
import SubmitTask from "../pages/SubmitTask";
import TaskViewer from "../pages/TaskViewer";
import TaskHistory from "../pages/TaskHistory";
import ScheduledTasks from "../pages/ScheduledTasks";
import ScheduledTaskForm from "../pages/ScheduledTaskForm";
import ScheduledTaskDetail from "../pages/ScheduledTaskDetail";
import Files from "../pages/Files";
import Snapshots from "../pages/Snapshots";
import Console from "../pages/Console";
import Templates from "../pages/settings/Templates";
import TemplateForm from "../pages/settings/TemplateForm";
import Skills from "../pages/settings/Skills";
import SkillEditor from "../pages/settings/SkillEditor";
import Mcp from "../pages/settings/Mcp";
import McpEditor from "../pages/settings/McpEditor";
import Users from "../pages/settings/Users";
import ApiKeys from "../pages/settings/ApiKeys";
import Credentials from "../pages/settings/Credentials";
import Profile from "../pages/settings/Profile";
import CreateContainer from "../pages/CreateContainer";
import StaffArea from "../pages/staff/StaffArea";
import StaffUsers from "../pages/staff/StaffUsers";
import Tasks from "../pages/Tasks";
import Prompts from "../pages/prompts/Prompts";
import PromptForm from "../pages/prompts/PromptForm";
import Workflows from "../pages/workflows/Workflows";
import WorkflowForm from "../pages/workflows/WorkflowForm";
import WorkflowDetail from "../pages/workflows/WorkflowDetail";
import WorkflowRunDetail from "../pages/workflows/WorkflowRunDetail";

export const routes: RouteObject[] = [
  { path: "/login", element: <AuthProvider><Login /></AuthProvider> },
  { path: "/change-password", element: <AuthProvider><RequireRole><ChangePassword /></RequireRole></AuthProvider> },
  {
    path: "/",
    element: <AuthProvider><RequireRole><AppShell /></RequireRole></AuthProvider>,
    children: [
      { index: true, element: <Dashboard /> },
      { path: "tasks", element: <Tasks /> },
      { path: "containers", element: <Containers /> },
      { path: "containers/new", element: <CreateContainer /> },
      {
        path: "containers/:cid",
        element: <ContainerLayout />,
        children: [
          { index: true, element: <ContainerOverview /> },
          { path: "config", element: <Configuration /> },
          { path: "files", element: <Files /> },
          { path: "snapshots", element: <Snapshots /> },
          { path: "submit", element: <SubmitTask /> },
          { path: "console", element: <Console /> },
          { path: "tasks/:tid", element: <TaskViewer /> },
          { path: "history", element: <TaskHistory /> },
        ],
      },
      { path: "schedules", element: <ScheduledTasks /> },
      { path: "schedules/new", element: <ScheduledTaskForm /> },
      { path: "schedules/:sid", element: <ScheduledTaskDetail /> },
      { path: "schedules/:sid/edit", element: <ScheduledTaskForm /> },
      { path: "settings/templates", element: <Templates /> },
      { path: "settings/templates/new", element: <RequireRole min="admin"><TemplateForm /></RequireRole> },
      { path: "settings/templates/:id/edit", element: <RequireRole min="admin"><TemplateForm /></RequireRole> },
      { path: "settings/skills", element: <RequireRole min="admin"><Skills /></RequireRole> },
      { path: "settings/skills/new", element: <RequireRole min="admin"><SkillEditor /></RequireRole> },
      { path: "settings/skills/:id/edit", element: <RequireRole min="admin"><SkillEditor /></RequireRole> },
      { path: "settings/mcp", element: <RequireRole min="admin"><Mcp /></RequireRole> },
      { path: "settings/mcp/new", element: <RequireRole min="admin"><McpEditor /></RequireRole> },
      { path: "settings/mcp/:id/edit", element: <RequireRole min="admin"><McpEditor /></RequireRole> },
      { path: "settings/users", element: <RequireRole min="admin"><Users /></RequireRole> },
      { path: "settings/api-keys", element: <RequireRole min="admin"><ApiKeys /></RequireRole> },
      { path: "settings/credentials", element: <RequireRole min="admin"><Credentials /></RequireRole> },
      { path: "profile", element: <Profile /> },
      { path: "prompts", element: <Prompts /> },
      { path: "prompts/new", element: <PromptForm /> },
      { path: "prompts/:id/edit", element: <PromptForm /> },
      { path: "workflows", element: <Workflows /> },
      { path: "workflows/new", element: <WorkflowForm /> },
      { path: "workflows/:id/edit", element: <WorkflowForm /> },
      { path: "workflows/:id", element: <WorkflowDetail /> },
      { path: "workflows/:id/runs/:runId", element: <WorkflowRunDetail /> },
      { path: "staff", element: <RequireRole staff><StaffArea /></RequireRole> },
      { path: "staff/users", element: <RequireRole staff><StaffUsers /></RequireRole> },
      { path: "*", element: <Navigate to="/" replace /> },
    ],
  },
];

export const router = createBrowserRouter(routes);
