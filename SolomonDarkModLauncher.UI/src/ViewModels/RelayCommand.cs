using System.Windows.Input;

namespace SolomonDarkModLauncher.UI.ViewModels;

internal sealed class RelayCommand : ICommand
{
    private readonly Action<object?> execute_;
    private readonly Predicate<object?>? canExecute_;

    public RelayCommand(Action<object?> execute, Predicate<object?>? canExecute = null)
    {
        execute_ = execute;
        canExecute_ = canExecute;
    }

    public event EventHandler? CanExecuteChanged;

    public bool CanExecute(object? parameter)
    {
        return canExecute_?.Invoke(parameter) ?? true;
    }

    public void Execute(object? parameter)
    {
        execute_(parameter);
    }

    public void RaiseCanExecuteChanged()
    {
        CanExecuteChanged?.Invoke(this, EventArgs.Empty);
    }
}
