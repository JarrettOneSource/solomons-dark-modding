struct SDModHubSurfaceState {
    bool valid = false;
    bool shared_hub = false;
    bool chat_active = false;
    bool surface_active = false;
    bool inventory_screen_active = false;
    bool inventory_shop_active = false;
    uintptr_t gameplay_address = 0;
    uintptr_t courtyard_address = 0;
    uintptr_t surface_address = 0;
    uintptr_t surface_vtable = 0;
    uintptr_t shop_address = 0;
    uintptr_t shop_vtable = 0;
};
