# -----------------------------------------------------------------------------------------------------
import torch as tt
import torch.nn as nn
from torch.optim import lr_scheduler
import numpy as np
from torch.utils.data import Dataset, DataLoader
from .common import save_state, load_state
import matplotlib.pyplot as plt
# -----------------------------------------------------------------------------------------------------
import datetime
now = datetime.datetime.now


class QuantiyMonitor:
    """ Monitors a quantity overtime to check if it improves(decrease) after a given patience. """

    def __init__(self, name, patience, delta):
        assert(patience>0) # patience should be positive
        assert(delta>0) # delta should be positive
        self.patience, self.delta = patience, delta
        self.name = name
        self.reset()
    
    def reset(self, initial=None):
        self.last = (tt.inf if initial is None else initial)
        self.best = self.last
        self.counter = 0
        self.best_epoch = -1

    def __call__(self, current, epoch=-1, verbose=False):
        self.last = current
        if self.best == tt.inf: 
            self.best=self.last
            self.best_epoch = epoch
            if verbose: print(f'|~|\t{self.name} Set to [{self.best}] on epoch {epoch}')
        else:
            delta = self.best - current # `loss` has decreased if `delta` is positive
            if delta > self.delta:
                # loss decresed more than self.delta
                if verbose: print(f'|~|\t{self.name} Decreased by [{delta}] on epoch {epoch}') # {self.best} --> {current}, 
                self.best = current
                self.best_epoch = epoch
                self.counter = 0
            else:
                # loss didnt decresed more than self.delta
                self.counter += 1
                if self.counter >= self.patience: 
                    if verbose: print(f'|~| Stopping on {self.name} = [{current}] @ epoch {epoch} | best value = [{self.best}] @ epoch {self.best_epoch}')
                    return True # end of patience
        return False

class Trainer:
    
    def __init__(self, 
            model, criterionF, criterionA, optimizerF, optimizerA, 
            training_data, validation_data, testing_data, loss_delta, loss_patience, val_loss_delta, val_loss_patience,
            save_path, save_state_only) -> None:
        if criterionA is None: criterionA = {}
        if optimizerA is None: optimizerA = {}

        self.model = model
        self.criterion = criterionF(**criterionA)
        self.optimizer = optimizerF(self.model.parameters(), **optimizerA)
        self.set_training_data(training_data)
        self.set_validation_data(validation_data)
        self.set_testing_data(testing_data)

        self.early_stop_train = None
        self.early_stop_val = None
        self.set_early_stop_training(loss_delta, loss_patience)
        self.set_early_stop_validation(val_loss_delta, val_loss_patience)
        self.save_path=save_path
        self.save_state_only = save_state_only

    def set_training_data(self, dataset): self.training_data = dataset
    
    def set_validation_data(self, dataset): self.validation_data = dataset

    def set_validation_data(self, dataset): self.testing_data = dataset

    def set_early_stop_training(self, delta, patience):
        if self.early_stop_train is None:
            if (delta is not None) and (patience is not None):
                self.early_stop_train = QuantiyMonitor('Training Loss', patience, delta)
        else:
            if (delta is not None) and (patience is not None):
                self.early_stop_train = QuantiyMonitor('Training Loss', patience, delta)
            else:
                self.early_stop_train = None

    def set_early_stop_validation(self, delta, patience):
        if self.early_stop_val is None:
            if (delta is not None) and (patience is not None):
                self.early_stop_val = QuantiyMonitor('Validation Loss', patience, delta)
        else:
            if (delta is not None) and (patience is not None):
                self.early_stop_val = QuantiyMonitor('Validation Loss', patience, delta)
            else:
                self.early_stop_val = None

    def do_save(self):
        if self.save_path:
            _ = (save_state(self.save_path, self.model) if self.save_state_only else tt.save(self.save_path, self.model))
            return True
        return False

    def train_step(self, data_loader):
        self.model.train()
        batch_loss=[]
        for i,(X,Y) in enumerate(data_loader, 0):
            self.optimizer.zero_grad()
            P = self.model(X)
            loss = self.criterion(P, Y)
            loss.backward()
            self.optimizer.step()
            batch_loss.append(loss.item())
        return batch_loss

    def test_step_single(self, data_loader):
        self.model.eval()
        with tt.no_grad():
            Xv,Yv = next(iter(data_loader)) # assume batch_size = len(validation_data_loader.dataset)
            Pv = self.model(Xv)
            tloss = self.criterion(Pv, Yv).item()
        return tloss

    def test_step_batch(self, data_loader):
        self.model.eval()
        tloss = []
        with tt.no_grad():
            for iv,(Xv,Yv) in enumerate(data_loader, 0):  # assume batch_size < len(validation_data_loader.dataset)
                Pv = self.model(Xv)
                tloss.append(self.criterion(Pv, Yv).item())
        return np.mean(tloss)

    def do_train(self,
                epochs=0, batch_size=0, shuffle=None, validation_freq=0, lrs=None,
                record_batch_loss=False, checkpoint_freq=0, verbose=0, plot=0):

        assert epochs>0, f'Epochs should be at least 1'
        assert batch_size>0, f'Batch Size should be at least 1'
        assert self.training_data is not None, f'Training data not available'
        assert self.criterion is not None, f'Loss Criterion not available'
        assert self.optimizer is not None, f'Optimizer not available'

        do_validation = ((validation_freq>0) and (self.validation_data is not None))
        do_checkpoint = ((checkpoint_freq>0) and (self.save_path))
        

        start_time=now()
        if verbose: print('Start Training @ {}'.format(start_time))

        loss_history = []
        training_data_loader = DataLoader(self.training_data, batch_size=batch_size, shuffle=shuffle)
        if verbose: 
            print(f'Training samples: [{len(self.training_data)}]')
            print(f'Training batches: [{len(training_data_loader)}]')

        if do_validation: 
            val_loss_history=[]
            validation_data_loader = DataLoader(self.validation_data, batch_size=len(self.validation_data), shuffle=False)
            val_step = lambda: self.test_step_single(validation_data_loader)
            if verbose: 
                print(f'Validation samples: [{len(self.validation_data)}]')
                print(f'Validation batches: [{len(validation_data_loader)}]')

        lr_history = []
        lrs = (lr_scheduler.ConstantLR(self.optimizer, factor=1.0, total_iters=epochs) \
            if lrs is None else lrs)
        early_stop=False
        if verbose: print('-------------------------------------------')
        for epoch in range(1, epochs+1):
            if verbose>1: print(f'[+] Epoch {epoch} of {epochs}')
            lr_history.append(lrs.get_last_lr())

            batch_loss = self.train_step()
            mean_batch_loss = np.mean(batch_loss)
            if verbose>1:
                print(f'(-)\tTraining Loss: {mean_batch_loss}')
                if verbose>2: 
                    for i,loss_value in enumerate(batch_loss): print(f'(----) Batch {i+1}\t Loss: {loss_value}')

            if record_batch_loss:
                loss_history.extend(batch_loss)
            else:
                loss_history.append(mean_batch_loss)

            if self.early_stop_train is not None: early_stop=self.early_stop_train(mean_batch_loss, epoch, verbose>1)
            
            lrs.step()

            if do_checkpoint:
                if (epoch%checkpoint_freq==0):
                    saved = self.do_save()
                    if saved and verbose>1: print(f'(-)\tCheckpoint created on epoch {epoch}')

            if do_validation:
                if (epoch%validation_freq==0):
                    vloss = val_step()
                    val_loss_history.append(vloss)
                    if verbose>1: print(f'(-)\tValidation Loss: {vloss}')
                    if self.early_stop_val is not None: early_stop=self.early_stop_val(vloss, epoch, verbose>1)

            if early_stop: 
                if verbose: print(f'[~] Early-Stopping on epoch {epoch}')
                break
        # end for epochs...................................................
        saved = self.do_save()
        if saved and verbose: print(f'[*] Saved @ {self.save_path}')
        if verbose: print('-------------------------------------------')
        end_time=now()
        if verbose:
            print(f'Final Training Loss: [{loss_history[-1]}]')
            if do_validation: print(f'Final Validation Loss: [{val_loss_history[-1]}]') 
            print('End Training @ {}, Elapsed Time: [{}]'.format(end_time, end_time-start_time))

        if (self.testing_data is not None):
            testing_data_loader = DataLoader(self.testing_data, batch_size=len(self.testing_data), shuffle=False)
            tloss = self.test_step_single(testing_data_loader)
            if verbose: 
                print(f'Testing samples: [{len(self.testing_data)}]')
                print(f'Testing batches: [{len(testing_data_loader)}]')
                print(f'Testing Loss: [{tloss}]') 
        else:
            tloss=None

        history = {
            'lr':       lr_history, 
            'loss':     loss_history,
            'val_loss': (val_loss_history if do_validation else [None]),
            'test_loss': tloss,
            }
        if plot: __class__.plot_results(history)
        return history

    def plot_results(history):
            plt.figure(figsize=(12,6))
            plt.title('Training Loss')
            plt.plot(history['loss'],color='tab:red', label='train_loss')
            plt.legend()
            plt.show()
            plt.close()
            if 'val_loss' in history:
                plt.figure(figsize=(12,6))
                plt.title('Validation Loss')
                plt.plot(history['val_loss'],color='tab:orange', label='val_loss')
                plt.legend()
                plt.show()
                plt.close()
            plt.figure(figsize=(12,6))
            plt.title('Learning Rate')
            plt.plot(history['lr'],color='tab:green', label='learning_rate')
            plt.legend()
            plt.show()
            plt.close()



def train(model, training_data=None, validation_data=None, testing_data=None,
            epochs=0, batch_size=0, shuffle=None, validation_freq=0, 
            criterion_type=None, criterion_args={}, optimizer_type=None, optimizer_args={}, lrs_type=None, lrs_args={},
            record_batch_loss=False, early_stop_train=None, early_stop_val=None, checkpoint_freq=0, save_path=None,
            save_state_only=False, verbose=0, plot=0, loss_plot_start=0):
            
    assert criterion_type is not None, f'Loss Criterion not provided'
    assert optimizer_type is not None, f'Optimizer not provided'
    criterion=criterion_type(**criterion_args)
    optimizer=optimizer_type(model.parameters(), **optimizer_args)
    lrs=(lr_scheduler.ConstantLR(optimizer, factor=1.0, total_iters=epochs) \
        if lrs_type is None else lrs_type(optimizer, **lrs_args))
    return train_(model, training_data, validation_data, testing_data,
            epochs, batch_size, shuffle, validation_freq, 
            criterion, optimizer, lrs, record_batch_loss, 
            early_stop_train, early_stop_val, checkpoint_freq, save_path,
            save_state_only, verbose, plot, loss_plot_start)

def train_(model, training_data=None, validation_data=None, testing_data=None,
            epochs=0, batch_size=0, shuffle=None, validation_freq=0, 
            criterion=None, optimizer=None, lrs=None,
            record_batch_loss=False, early_stop_train=None, early_stop_val=None, checkpoint_freq=0, save_path=None,
            save_state_only=False, verbose=0, plot=0, loss_plot_start=0):

    assert epochs>0, f'Epochs should be at least 1'
    assert batch_size>0, f'Batch Size should be at least 1'
    assert training_data is not None, f'Training data not provided'
    
    if validation_data is not None: 
        if validation_freq<=0: print(f'[!] Validation data is provided buy frequency not set, Validation will not be performed')
    
    assert criterion is not None, f'Loss Criterion not provided'
    assert optimizer is not None, f'Optimizer not provided'

    do_validation = ((validation_freq>0) and (validation_data is not None))
    do_checkpoint = ((checkpoint_freq>0) and (save_path))

    start_time=now()
    if verbose: print('Start Training @ {}'.format(start_time))

    loss_history = []
    training_data_loader = DataLoader(training_data, batch_size=batch_size, shuffle=shuffle)
    if verbose: 
        print(f'Training samples: [{len(training_data)}]')
        print(f'Training batches: [{len(training_data_loader)}]')

    if validation_data is not None: 
        val_loss_history=[]
        validation_data_loader = DataLoader(validation_data, batch_size=len(validation_data), shuffle=False)
        if verbose: 
            print(f'Validation samples: [{len(validation_data)}]')
            print(f'Validation batches: [{len(validation_data_loader)}]')

    lr_history = []
    lrs = (lr_scheduler.ConstantLR(optimizer, factor=1.0, total_iters=epochs) if lrs is None else lrs)
    early_stop=False
    if verbose: print('-------------------------------------------')
    for epoch in range(1, epochs+1):
        if verbose>1: print(f'[+] Epoch {epoch} of {epochs}')
        lr_history.append(lrs.get_last_lr())
        model.train()
        batch_loss=[]
        for i,(X,Y) in enumerate(training_data_loader, 0):
            optimizer.zero_grad()
            P = model(X)
            loss = criterion(P, Y)
            loss.backward()
            optimizer.step()
            loss_value = loss.item()
            batch_loss.append(loss_value)
            if verbose>2: print(f'[++] Batch {i+1}\t Loss: {loss_value}')
        lrs.step()
        mean_batch_loss = np.mean(batch_loss)
        if verbose>1: print(f'(-)\tTraining Loss: {mean_batch_loss}')
        if record_batch_loss:
            loss_history.extend(batch_loss)
        else:
            loss_history.append(mean_batch_loss)
        if early_stop_train is not None: early_stop=early_stop_train(mean_batch_loss, epoch, verbose>1)
            
        if do_checkpoint:
            if (epoch%checkpoint_freq==0):
                if save_state_only:
                    save_state(save_path, model)
                else:
                    tt.save(save_path, model)
                if verbose>1: print(f'(-)\tCheckpoint created on epoch {epoch}')


        if do_validation:
            if (epoch%validation_freq==0):
                model.eval()
                with tt.no_grad():
                    for iv,(Xv,Yv) in enumerate(validation_data_loader, 0):
                        Pv = model(Xv)
                        vloss = criterion(Pv, Yv).item()
                        val_loss_history.append(vloss)
                if verbose>1: print(f'(-)\tValidation Loss: {vloss}')
                if early_stop_val is not None: early_stop=early_stop_val(vloss, epoch, verbose>1)

        if early_stop: 
            if verbose: print(f'[~] Early-Stopping on epoch {epoch}')
            break
    # end for epochs...................................................

    if save_path: 
        if save_state_only:
            save_state(save_path, model)
        else:
            tt.save(save_path, model)
        if verbose: print(f'[*] Saved @ {save_path}')
    if verbose: print('-------------------------------------------')
    end_time=now()
    if verbose:
        print(f'Final Training Loss: [{loss_history[-1]}]')
        if do_validation: print(f'Final Validation Loss: [{val_loss_history[-1]}]') 
        print('End Training @ {}, Elapsed Time: [{}]'.format(end_time, end_time-start_time))

    if (testing_data is not None):
        testing_data_loader = DataLoader(testing_data, batch_size=len(testing_data), shuffle=False)
        model.eval()
        with tt.no_grad():
            for iv,(Xv,Yv) in enumerate(testing_data_loader, 0):
                Pv = model(Xv)
                tloss = criterion(Pv, Yv).item()
        if verbose: 
            print(f'Testing samples: [{len(testing_data)}]')
            print(f'Testing batches: [{len(testing_data_loader)}]')
            print(f'Testing Loss: [{tloss}]') 
    else:
        tloss=None

    history = {
        'lr':       lr_history, 
        'loss':     loss_history,
        'val_loss': (val_loss_history if do_validation else [None]),
        'test_loss': tloss,
        }
    if plot:
        plt.figure(figsize=(12,6))
        plt.title('Training Loss')
        plt.plot(history['loss'][loss_plot_start:],color='tab:red', label='train_loss')
        plt.legend()
        plt.show()
        plt.close()
        if do_validation:
            plt.figure(figsize=(12,6))
            plt.title('Validation Loss')
            plt.plot(history['val_loss'],color='tab:orange', label='val_loss')
            plt.legend()
            plt.show()
            plt.close()
        plt.figure(figsize=(12,6))
        plt.title('Learning Rate')
        plt.plot(history['lr'],color='tab:green', label='learning_rate')
        plt.legend()
        plt.show()
        plt.close()
        
    return history
