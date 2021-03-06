import { NgModule } from '@angular/core';
import { BrowserModule } from '@angular/platform-browser';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';

import { SharedModule } from '../shared.module';

import { ClustersComponent } from './index';

@NgModule({
  declarations: [
    ClustersComponent
  ],
  imports: [
    BrowserModule,
    RouterModule,
    FormsModule,
    SharedModule
  ],
  exports: [
    ClustersComponent
  ]
})
export class ClustersModule { }
