// MIT. Native Explorer command: receives the entire shell selection.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shobjidl.h>
#include <shlobj.h>
#include <string>
#include <vector>
#include <new>

// Keep in sync with easysync.shellmenu.SHELL_CLSID.
const CLSID CLSID_EasySync = {0x94c31a68,0x063e,0x4ef3,{0xb0,0xe9,0x8d,0x15,0xb7,0x79,0x4e,0x2a}};
static LONG objects = 0;
static const wchar_t* ConfigKey = L"Software\\EasySync\\ShellImport";

static std::wstring setting(const wchar_t* name) {
    DWORD bytes = 0;
    if (RegGetValueW(HKEY_CURRENT_USER, ConfigKey, name, RRF_RT_REG_SZ,
                    nullptr, nullptr, &bytes) != ERROR_SUCCESS) return {};
    std::vector<wchar_t> value(bytes / sizeof(wchar_t) + 1);
    if (RegGetValueW(HKEY_CURRENT_USER, ConfigKey, name, RRF_RT_REG_SZ,
                    nullptr, value.data(), &bytes) != ERROR_SUCCESS) return {};
    return value.data();
}

static HRESULT launch(IShellItemArray* selection) {
    const auto program = setting(L"Program"), script = setting(L"Script");
    if (program.empty() || !selection) return E_INVALIDARG;
    DWORD count = 0;
    HRESULT hr = selection->GetCount(&count);
    if (FAILED(hr) || !count) return FAILED(hr) ? hr : E_INVALIDARG;
    std::wstring paths;
    for (DWORD i = 0; i < count; ++i) {
        IShellItem* item = nullptr;
        hr = selection->GetItemAt(i, &item);
        if (FAILED(hr)) return hr;
        PWSTR path = nullptr;
        hr = item->GetDisplayName(SIGDN_FILESYSPATH, &path);
        item->Release();
        if (FAILED(hr)) return hr;
        try {
            paths += path;
            paths += L'\n';
        } catch (...) {
            CoTaskMemFree(path);
            throw;
        }
        CoTaskMemFree(path);
        if (paths.size() > 64 * 1024 * 1024) return E_INVALIDARG;
    }
    const int size = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS,
        paths.data(), static_cast<int>(paths.size()), nullptr, 0, nullptr, nullptr);
    if (size <= 0 || size > 64 * 1024 * 1024) return E_INVALIDARG;
    std::string utf8(size, '\0');
    if (!WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, paths.data(),
        static_cast<int>(paths.size()), utf8.data(), size, nullptr, nullptr))
        return HRESULT_FROM_WIN32(GetLastError());
    wchar_t temp[MAX_PATH + 1];
    DWORD length = GetTempPathW(MAX_PATH + 1, temp);
    if (!length || length > MAX_PATH) return E_FAIL;
    std::wstring folder = std::wstring(temp) + L"EasySync-Selections";
    if (!CreateDirectoryW(folder.c_str(), nullptr) && GetLastError() != ERROR_ALREADY_EXISTS)
        return HRESULT_FROM_WIN32(GetLastError());
    GUID id;
    if (FAILED(CoCreateGuid(&id))) return E_FAIL;
    wchar_t guid[40];
    StringFromGUID2(id, guid, 40);
    const auto manifest = folder + L"\\" + guid + L".paths";
    HANDLE file = CreateFileW(manifest.c_str(), GENERIC_WRITE, 0, nullptr,
        CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) return HRESULT_FROM_WIN32(GetLastError());
    DWORD written = 0;
    BOOL ok = WriteFile(file, utf8.data(), size, &written, nullptr);
    DWORD error = ok ? ERROR_WRITE_FAULT : GetLastError();
    CloseHandle(file);
    if (!ok || written != static_cast<DWORD>(size)) {
        DeleteFileW(manifest.c_str());
        return HRESULT_FROM_WIN32(error);
    }
    auto quote = [](const std::wstring& value) { return L"\"" + value + L"\""; };
    auto command = quote(program);
    if (!script.empty()) command += L" " + quote(script);
    command += L" --shell-selection " + quote(manifest);
    STARTUPINFOW startup = {sizeof(startup)};
    PROCESS_INFORMATION process = {};
    ok = CreateProcessW(program.c_str(), command.data(), nullptr, nullptr, FALSE,
        CREATE_NO_WINDOW, nullptr, nullptr, &startup, &process);
    if (!ok) {
        error = GetLastError();
        DeleteFileW(manifest.c_str());
        return HRESULT_FROM_WIN32(error);
    }
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return S_OK;
}

class Command final : public IExecuteCommand, public IObjectWithSelection,
                      public IInitializeCommand {
    LONG refs = 1;
    IShellItemArray* selection = nullptr;
public:
    Command() { InterlockedIncrement(&objects); }
    ~Command() {
        if (selection) selection->Release();
        InterlockedDecrement(&objects);
    }
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void** out) override {
        if (!out) return E_POINTER;
        *out = nullptr;
        if (iid == IID_IUnknown || iid == __uuidof(IExecuteCommand))
            *out = static_cast<IExecuteCommand*>(this);
        else if (iid == __uuidof(IObjectWithSelection))
            *out = static_cast<IObjectWithSelection*>(this);
        else if (iid == __uuidof(IInitializeCommand))
            *out = static_cast<IInitializeCommand*>(this);
        else return E_NOINTERFACE;
        AddRef(); return S_OK;
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return InterlockedIncrement(&refs); }
    ULONG STDMETHODCALLTYPE Release() override {
        ULONG result = InterlockedDecrement(&refs);
        if (!result) delete this;
        return result;
    }
    HRESULT STDMETHODCALLTYPE Initialize(LPCWSTR, IPropertyBag*) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE SetSelection(IShellItemArray* value) override {
        if (value) value->AddRef();
        if (selection) selection->Release();
        selection = value; return S_OK;
    }
    HRESULT STDMETHODCALLTYPE GetSelection(REFIID iid, void** out) override {
        if (!out) return E_POINTER;
        *out = nullptr;
        return selection ? selection->QueryInterface(iid, out) : E_FAIL;
    }
    HRESULT STDMETHODCALLTYPE SetKeyState(DWORD) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE SetParameters(LPCWSTR) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE SetPosition(POINT) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE SetShowWindow(int) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE SetNoShowUI(BOOL) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE SetDirectory(LPCWSTR) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE Execute() override {
        try { return launch(selection); } catch (...) { return E_OUTOFMEMORY; }
    }
};

class Factory final : public IClassFactory {
    LONG refs = 1;
public:
    Factory() { InterlockedIncrement(&objects); }
    ~Factory() { InterlockedDecrement(&objects); }
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void** out) override {
        if (!out) return E_POINTER;
        *out = nullptr;
        if (iid != IID_IUnknown && iid != IID_IClassFactory) return E_NOINTERFACE;
        *out = static_cast<IClassFactory*>(this); AddRef(); return S_OK;
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return InterlockedIncrement(&refs); }
    ULONG STDMETHODCALLTYPE Release() override {
        ULONG result = InterlockedDecrement(&refs);
        if (!result) delete this;
        return result;
    }
    HRESULT STDMETHODCALLTYPE CreateInstance(IUnknown* outer, REFIID iid, void** out) override {
        if (!out) return E_POINTER;
        *out = nullptr;
        if (outer) return CLASS_E_NOAGGREGATION;
        auto command = new(std::nothrow) Command;
        if (!command) return E_OUTOFMEMORY;
        HRESULT hr = command->QueryInterface(iid, out);
        command->Release(); return hr;
    }
    HRESULT STDMETHODCALLTYPE LockServer(BOOL lock) override {
        if (lock) InterlockedIncrement(&objects); else InterlockedDecrement(&objects);
        return S_OK;
    }
};

STDAPI DllGetClassObject(REFCLSID clsid, REFIID iid, void** out) {
    if (!out) return E_POINTER;
    *out = nullptr;
    if (clsid != CLSID_EasySync) return CLASS_E_CLASSNOTAVAILABLE;
    auto factory = new(std::nothrow) Factory;
    if (!factory) return E_OUTOFMEMORY;
    HRESULT hr = factory->QueryInterface(iid, out);
    factory->Release();
    return hr;
}

STDAPI DllCanUnloadNow() {
    return InterlockedCompareExchange(&objects, 0, 0) == 0 ? S_OK : S_FALSE;
}
