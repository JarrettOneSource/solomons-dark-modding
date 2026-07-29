#pragma once

#include <string>

namespace sdmod {

bool InitializeHeadlessSimulation(std::string* error_message);
void ObserveHeadlessSimulationWindow(void* window);
void PrepareHeadlessSimulationTick(
    void* app,
    bool simulation_scene_active);
void FinishHeadlessSimulationTick(void* app);
bool IsHeadlessSimulationEnabled();
void ShutdownHeadlessSimulation();

}  // namespace sdmod
