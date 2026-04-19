float EstimateGameplayPathHeuristic(int grid_x, int grid_y, int goal_grid_x, int goal_grid_y) {
    const auto dx = static_cast<float>(std::abs(goal_grid_x - grid_x));
    const auto dy = static_cast<float>(std::abs(goal_grid_y - grid_y));
    const auto diagonal = dx < dy ? dx : dy;
    const auto straight = (dx > dy ? dx : dy) - diagonal;
    return diagonal * 1.41421356237f + straight;
}

void ResetBotPathState(ParticipantEntityBinding* binding) {
    if (binding == nullptr) {
        return;
    }

    binding->path_active = false;
    binding->path_failed = false;
    binding->active_path_revision = 0;
    binding->path_waypoint_index = 0;
    binding->current_waypoint_x = 0.0f;
    binding->current_waypoint_y = 0.0f;
    binding->path_waypoints.clear();
}

void StopBotPathMotion(ParticipantEntityBinding* binding, bool preserve_path) {
    if (binding == nullptr) {
        return;
    }

    binding->movement_active = false;
    binding->direction_x = 0.0f;
    binding->direction_y = 0.0f;
    binding->current_waypoint_x = 0.0f;
    binding->current_waypoint_y = 0.0f;
    if (!preserve_path) {
        ResetBotPathState(binding);
    }
}

